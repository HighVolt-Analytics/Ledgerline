"""Dual-currency journal FX helpers and accrual/settlement behaviour."""

from datetime import date, datetime, timezone
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.schemas.rule_book_config import PostingDefaults, RuleBookConfigPayload
from app.services.payments.journal_fx import (
    FX_SOURCE_IDENTITY,
    FX_SOURCE_PAYMENT_APP,
    FX_SOURCE_PENDING_PAYMENT,
    apply_line_fx,
    invoice_currency_code,
    resolve_accrual_fx,
    resolve_payment_fx,
)
from app.services.payments.journal_generator import generate_entries, is_balanced
from app.services.payments.settlement_journal_service import generate_payment_settlement_entries
from app.services.rule_book.account_mapper import AccountMapping


def test_invoice_currency_code_blank_is_unknown() -> None:
    inv = Invoice(tenant_id=None, currency="", status=InvoiceStatus.PROCESSED)
    assert invoice_currency_code(inv) == "UNKNOWN"


def test_resolve_accrual_fx_same_currency_identity() -> None:
    rate, _, source = resolve_accrual_fx(txn_currency="AUD", base_currency="AUD")
    assert rate == Decimal("1")
    assert source == FX_SOURCE_IDENTITY


def test_resolve_accrual_fx_foreign_pending_payment() -> None:
    rate, _, source = resolve_accrual_fx(txn_currency="INR", base_currency="AUD")
    assert rate is None
    assert source == FX_SOURCE_PENDING_PAYMENT


def test_generate_entries_foreign_invoice_keeps_txn_currency() -> None:
    inv = Invoice(
        tenant_id=None,
        invoice_date=date(2026, 5, 1),
        subtotal=Decimal("9744.61"),
        gst=Decimal("55.92"),
        total=Decimal("9800.53"),
        currency="INR",
        status=InvoiceStatus.JOURNALING,
    )
    lines = generate_entries(
        inv,
        AccountMapping("6100", "Operating Expenses"),
        base_currency="AUD",
    )
    assert is_balanced(lines)
    assert all(line.txn_currency == "INR" for line in lines)
    assert all(line.fx_source == FX_SOURCE_PENDING_PAYMENT for line in lines)
    assert all(line.base_debit is None for line in lines if line.debit > 0)


def test_generate_entries_aud_populates_base_amounts() -> None:
    inv = Invoice(
        tenant_id=None,
        invoice_date=date(2026, 5, 1),
        subtotal=Decimal("271.82"),
        gst=Decimal("27.18"),
        total=Decimal("299.00"),
        currency="AUD",
        status=InvoiceStatus.JOURNALING,
    )
    lines = generate_entries(
        inv,
        AccountMapping("6100", "Operating Expenses"),
        base_currency="AUD",
    )
    assert is_balanced(lines)
    expense = next(ln for ln in lines if ln.account_code == "6100")
    assert expense.txn_currency == "AUD"
    assert expense.base_debit == Decimal("271.82")
    assert expense.fx_rate == Decimal("1")
    assert expense.fx_source == FX_SOURCE_IDENTITY


def test_resolve_payment_fx_from_payment_app_fields() -> None:
    payment = Payment(
        tenant_id=None,
        invoice_id=1,
        amount=Decimal("9800.53"),
        currency="INR",
        status=PaymentStatus.PAID,
        payment_fx_rate=Decimal("0.018"),
        bank_payment_amount=Decimal("176.41"),
    )
    rate, bank, variance, source = resolve_payment_fx(payment, base_currency="AUD")
    assert rate == Decimal("0.018")
    assert bank == Decimal("176.41")
    assert source == FX_SOURCE_PAYMENT_APP
    assert variance == Decimal("0.00")


def test_payment_settlement_foreign_with_fx_posts_base_amounts() -> None:
    inv = Invoice(
        tenant_id=None,
        invoice_date=date(2026, 5, 1),
        total=Decimal("9800.53"),
        currency="INR",
        status=InvoiceStatus.PROCESSED,
    )
    payment = Payment(
        tenant_id=None,
        invoice_id=1,
        amount=Decimal("9800.53"),
        currency="INR",
        status=PaymentStatus.PAID,
        paid_date=datetime(2026, 5, 10, tzinfo=timezone.utc),
        payment_fx_rate=Decimal("0.018"),
        bank_payment_amount=Decimal("176.41"),
    )
    config = RuleBookConfigPayload(
        posting_defaults=PostingDefaults(
            payable_account="Accounts Payable",
            tax_account="GST Paid",
            bank_account="Bank Account",
        )
    )
    lines = generate_payment_settlement_entries(
        payment,
        inv,
        config,
        base_currency="AUD",
    )
    assert is_balanced(lines)
    payable = next(ln for ln in lines if "Payable" in ln.account_name)
    bank = next(ln for ln in lines if "Bank" in ln.account_name)
    assert payable.debit == Decimal("176.41")
    assert bank.credit == Decimal("176.41")
    assert payable.txn_currency == "INR"
    assert payable.fx_source == FX_SOURCE_PAYMENT_APP


def test_apply_line_fx_identity() -> None:
    fields = apply_line_fx(
        debit=Decimal("100.00"),
        credit=Decimal("0"),
        txn_currency="AUD",
        base_currency="AUD",
        fx_rate=Decimal("1"),
        fx_source=FX_SOURCE_IDENTITY,
    )
    assert fields["base_debit"] == Decimal("100.00")
    assert fields["base_credit"] == Decimal("0.00")
