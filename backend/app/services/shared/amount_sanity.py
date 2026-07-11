"""Reject OCR amounts that cannot fit invoice money columns."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.services.invoice.invoice_data import ParsedLineItem

_MAX_MONEY = Decimal("9999999999.99")
_MAX_QTY = Decimal("99999999.9999")
_MAX_GST_RATE = Decimal("999.99")
_REASONABLE_GST_RATE = Decimal("100")
_MAX_CONFIDENCE = Decimal("9.9999")


def plausible_money(value: Decimal | None) -> Decimal | None:
    """Drop values that overflow NUMERIC(12,2) or look like ABNs / IDs."""
    if value is None:
        return None
    abs_value = value.copy_abs()
    if abs_value > _MAX_MONEY:
        return None
    if abs_value >= Decimal("10000000"):
        return None
    return value


def plausible_qty(value: Decimal | None) -> Decimal | None:
    """Drop quantities that overflow NUMERIC(12,4) or look like IDs."""
    if value is None:
        return None
    abs_value = value.copy_abs()
    if abs_value > _MAX_QTY:
        return None
    if abs_value >= Decimal("10000000"):
        return None
    return value


def plausible_gst_rate_percent(value: Decimal | float | int | str | None) -> Decimal | None:
    """Keep tax rates within NUMERIC(5,2) and reject OCR garbage."""
    if value is None:
        return None
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None
    if value < 0:
        return None
    if value > _MAX_GST_RATE:
        return None
    if value > _REASONABLE_GST_RATE:
        return None
    return value.quantize(Decimal("0.01"))


def plausible_confidence(value: Decimal | float | int | str | None) -> Decimal | None:
    """Normalize confidence to 0–1 and fit NUMERIC(5,4)."""
    if value is None:
        return None
    try:
        raw = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if raw < 0:
        return None
    for _ in range(2):
        if raw.copy_abs() <= Decimal("1"):
            break
        raw = raw / Decimal("100")
    if raw.copy_abs() > Decimal("1"):
        return None
    if raw > _MAX_CONFIDENCE:
        raw = _MAX_CONFIDENCE
    return raw.quantize(Decimal("0.0001"))


def sanitize_parsed_line_item(
    item: ParsedLineItem,
    *,
    trace: object | None = None,
    row_key: str | None = None,
) -> ParsedLineItem:
    """Clamp parsed line numerics before persistence."""
    qty = plausible_qty(item.qty)
    unit_price = plausible_money(item.unit_price)
    amount = plausible_money(item.amount)
    tax_amount = plausible_money(item.tax_amount)
    if trace is not None and row_key:
        if item.qty is not None and qty is None:
            trace.record(row_key, "amount_sanity", "dropped", "implausible_qty")
        if item.unit_price is not None and unit_price is None:
            trace.record(row_key, "amount_sanity", "adjusted", "implausible_money")
        if item.amount is not None and amount is None:
            trace.record(row_key, "amount_sanity", "adjusted", "implausible_money")
    if amount is None and qty is not None and unit_price is not None:
        amount = plausible_money(qty * unit_price)
    if unit_price is None and amount is not None and qty is not None and qty > 0:
        unit_price = plausible_money(amount / qty)
    return ParsedLineItem(
        description=item.description,
        qty=qty,
        unit_price=unit_price,
        amount=amount,
        tax_amount=tax_amount,
        source=item.source,
        source_confidence=item.source_confidence,
        fused_from=list(item.fused_from) if item.fused_from else None,
    )
