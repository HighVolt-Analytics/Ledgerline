"""FX booking and payment variance tests."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice, InvoiceStatus
from app.models.purchase_order import PurchaseOrder
from app.schemas.fx_posting import FxPostingPolicy
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.account_mapper import AccountMapping
from app.services.fx_posting_service import (
    document_to_functional,
    generate_booking_entries,
    generate_payment_entries,
    po_invoice_currency_mismatch,
)
from app.services.journal_generator import generate_entries, is_balanced
from app.services.purchase_match_service import compute_three_way_match


def test_usd_invoice_books_aud_ap_at_invoice_rate() -> None:
    inv = Invoice(
        tenant_id=uuid4(),
        invoice_date=date(2026, 3, 1),
        subtotal=Decimal("1000"),
        gst=Decimal("100"),
        total=Decimal("1100"),
        currency="USD",
        status=InvoiceStatus.JOURNALING,
    )
    config = RuleBookConfigPayload()
    lines = generate_booking_entries(inv, AccountMapping("6100", "Supplies"), config=config)
    assert is_balanced(lines)
    assert inv.booking_fx_rate == Decimal("1.55")
    assert inv.functional_total == Decimal("1705.00")
    ap = [ln for ln in lines if ln.credit > 0][0]
    assert ap.credit == Decimal("1705.00")


def test_payment_fx_loss_when_spot_moves() -> None:
    policy = FxPostingPolicy()
    lines, variance = generate_payment_entries(
        functional_ap_amount=Decimal("1550.00"),
        bank_payment_amount=Decimal("1580.00"),
        policy=policy,
        payable_account_code="2000",
        payable_account_name="Accounts Payable",
        payment_date=date(2026, 4, 1),
    )
    assert is_balanced(lines)
    assert variance == Decimal("30.00")
    fx_line = next(ln for ln in lines if ln.account_code == "fx-gl")
    assert fx_line.debit == Decimal("30.00")


def test_po_invoice_currency_mismatch_flagged() -> None:
    policy = FxPostingPolicy(require_po_invoice_currency_match=True)
    po = PurchaseOrder(
        tenant_id=uuid4(),
        po_number="PO-USD-1",
        po_qty=Decimal("10"),
        po_unit_price=Decimal("100"),
        po_currency="USD",
    )
    inv = Invoice(
        tenant_id=po.tenant_id,
        currency="AUD",
        subtotal=Decimal("1000"),
        gst=Decimal("100"),
        total=Decimal("1100"),
        status=InvoiceStatus.PROCESSED,
    )
    match = compute_three_way_match(po, inv, fx_policy=policy)
    assert match.status == "Currency Mismatch"


def test_grn_aud_does_not_block_usd_po_invoice_qty_match() -> None:
    policy = FxPostingPolicy(grn_currency_operational_only=True)
    po = PurchaseOrder(
        tenant_id=uuid4(),
        po_number="PO-USD-2",
        po_qty=Decimal("1"),
        po_unit_price=Decimal("100"),
        po_currency="USD",
    )
    inv = Invoice(
        tenant_id=po.tenant_id,
        currency="USD",
        subtotal=Decimal("100"),
        gst=Decimal("10"),
        total=Decimal("110"),
        status=InvoiceStatus.PROCESSED,
    )
    grn = GoodsReceipt(
        tenant_id=po.tenant_id,
        purchase_order_id=1,
        grn_qty=Decimal("1"),
        grn_currency="AUD",
    )
    po.goods_receipts = [grn]
    match = compute_three_way_match(po, inv, fx_policy=policy)
    assert match.status == "3-Way Match"


def test_aud_invoice_unchanged() -> None:
    inv = Invoice(
        tenant_id=uuid4(),
        invoice_date=date(2026, 1, 15),
        subtotal=Decimal("500"),
        gst=Decimal("50"),
        total=Decimal("550"),
        currency="AUD",
        status=InvoiceStatus.JOURNALING,
    )
    lines = generate_entries(inv, AccountMapping("6200", "Supplies"))
    ap = [ln for ln in lines if ln.credit > 0][0]
    assert ap.credit == Decimal("550")
    assert inv.booking_fx_rate is None


def test_document_to_functional_usd() -> None:
    policy = FxPostingPolicy()
    amount, rate = document_to_functional(
        Decimal("1000"),
        "USD",
        policy=policy,
        booking_date=date(2026, 1, 1),
    )
    assert rate == Decimal("1.55")
    assert amount == Decimal("1550.00")


def test_po_invoice_currency_match_ok() -> None:
    policy = FxPostingPolicy()
    assert not po_invoice_currency_mismatch("USD", "USD", policy=policy)
    assert po_invoice_currency_mismatch("USD", "AUD", policy=policy)
