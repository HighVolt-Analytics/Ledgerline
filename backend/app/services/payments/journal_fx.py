"""Helpers for dual-currency journal and payment-time FX conversion."""

from __future__ import annotations

from decimal import Decimal

from app.models.invoice import Invoice
from app.models.payment import Payment
from app.services.shared.currency import UNKNOWN_CURRENCY

FX_SOURCE_IDENTITY = "identity"
FX_SOURCE_PENDING_PAYMENT = "pending_payment"
FX_SOURCE_PAYMENT_APP = "payment_app"
FX_SOURCE_LEGACY = "legacy_unconverted"


def normalize_txn_currency(currency: str | None) -> str:
    code = (currency or "").strip().upper()
    return code or UNKNOWN_CURRENCY


def invoice_currency_code(invoice: Invoice) -> str:
    return normalize_txn_currency(invoice.currency)


def round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def resolve_accrual_fx(
    *,
    txn_currency: str,
    base_currency: str,
) -> tuple[Decimal | None, Decimal | None, str]:
    """Return (fx_rate, base_amount_multiplier semantics, fx_source) for accrual.

    Accrual keeps document currency; base amounts are filled only when currencies match.
    Foreign invoices wait for payment-app conversion.
    """
    txn = normalize_txn_currency(txn_currency)
    base = (base_currency or "").strip().upper()
    if not base:
        return None, None, FX_SOURCE_LEGACY
    if txn == UNKNOWN_CURRENCY:
        return None, None, FX_SOURCE_LEGACY
    if txn == base:
        return Decimal("1"), Decimal("1"), FX_SOURCE_IDENTITY
    return None, None, FX_SOURCE_PENDING_PAYMENT


def apply_line_fx(
    *,
    debit: Decimal,
    credit: Decimal,
    txn_currency: str,
    base_currency: str,
    fx_rate: Decimal | None,
    fx_source: str,
) -> dict[str, Decimal | str | None]:
    """Build dual-currency fields for one journal line."""
    txn = normalize_txn_currency(txn_currency)
    base = (base_currency or "").strip().upper() or None
    rate = fx_rate
    source = fx_source
    base_debit: Decimal | None = None
    base_credit: Decimal | None = None

    if rate is not None and base:
        base_debit = round_money(debit * rate) if debit else Decimal("0.00")
        base_credit = round_money(credit * rate) if credit else Decimal("0.00")
    elif source == FX_SOURCE_IDENTITY and base:
        base_debit = round_money(debit)
        base_credit = round_money(credit)
        rate = Decimal("1")

    return {
        "txn_currency": None if txn == UNKNOWN_CURRENCY else txn,
        "base_currency": base,
        "base_debit": base_debit,
        "base_credit": base_credit,
        "fx_rate": rate,
        "fx_source": source,
    }


def resolve_payment_fx(
    payment: Payment,
    *,
    base_currency: str,
) -> tuple[Decimal | None, Decimal | None, Decimal | None, str]:
    """Return (fx_rate, bank_base_amount, fx_variance, fx_source) for settlement.

    Prefer explicit payment-app fields on the payment row. When currencies match,
    identity rate is used. Otherwise conversion waits for payment-app values.
    """
    base = (base_currency or "").strip().upper()
    txn = normalize_txn_currency(payment.currency)
    amount = Decimal(str(payment.amount or 0))

    explicit_rate = payment.payment_fx_rate
    bank_amount = payment.bank_payment_amount

    if txn != UNKNOWN_CURRENCY and base and txn == base:
        rate = Decimal("1")
        bank = round_money(amount)
        variance = Decimal("0.00")
        if bank_amount is not None:
            bank = round_money(Decimal(str(bank_amount)))
            variance = round_money(bank - amount)
        return rate, bank, variance, FX_SOURCE_IDENTITY

    if explicit_rate is not None and Decimal(str(explicit_rate)) > 0:
        rate = Decimal(str(explicit_rate))
        expected = round_money(amount * rate)
        bank = (
            round_money(Decimal(str(bank_amount)))
            if bank_amount is not None
            else expected
        )
        variance = round_money(bank - expected)
        return rate, bank, variance, FX_SOURCE_PAYMENT_APP

    if bank_amount is not None and amount > 0:
        bank = round_money(Decimal(str(bank_amount)))
        rate = (bank / amount).quantize(Decimal("0.00000001"))
        return rate, bank, Decimal("0.00"), FX_SOURCE_PAYMENT_APP

    return None, None, None, FX_SOURCE_PENDING_PAYMENT
