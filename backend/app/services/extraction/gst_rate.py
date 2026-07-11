"""Resolve GST/tax rate from extracted OCR fields or inferred amounts."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.invoice.invoice_data import InvoiceData
from app.services.shared.amount_sanity import plausible_gst_rate_percent

_GST_RATE_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def parse_gst_rate_percent(raw: Any) -> Decimal | None:
    """Parse a tax rate into percentage form (e.g. 10 for 10%)."""
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        value = raw
    elif isinstance(raw, (int, float)):
        value = Decimal(str(raw))
    elif isinstance(raw, str):
        token = raw.strip()
        if not token:
            return None
        match = _GST_RATE_PERCENT_RE.search(token)
        if match:
            token = match.group(1)
        else:
            token = token.replace("%", "").strip()
        if not token:
            return None
        try:
            value = Decimal(token)
        except InvalidOperation:
            return None
    else:
        return None

    if value < 0:
        return None
    if value <= Decimal("1"):
        value = (value * Decimal("100")).quantize(Decimal("0.01"))
    return plausible_gst_rate_percent(value.quantize(Decimal("0.01")))


def _rate_from_object(obj: object, *, allow_inference: bool = True) -> Decimal | None:
    direct = getattr(obj, "gst_rate", None)
    if direct is not None:
        parsed = parse_gst_rate_percent(direct)
        if parsed is not None:
            return parsed

    extracted = getattr(obj, "extracted_fields", None) or {}
    if isinstance(extracted, dict):
        parsed = parse_gst_rate_percent(extracted.get("gst_rate"))
        if parsed is not None:
            return parsed

    raw_fields = getattr(obj, "raw_fields", None) or {}
    if isinstance(raw_fields, dict):
        parsed = parse_gst_rate_percent(raw_fields.get("gst_rate"))
        if parsed is not None:
            return parsed

    if not allow_inference:
        return None

    subtotal = getattr(obj, "subtotal", None)
    gst = getattr(obj, "gst", None)
    if subtotal is not None and gst is not None and subtotal > 0:
        inferred = ((gst / subtotal) * Decimal("100")).quantize(Decimal("0.01"))
        return plausible_gst_rate_percent(inferred)
    return None


def resolve_gst_rate_percent(
    data: InvoiceData | object,
    *,
    ocr_text: str | None = None,
    allow_inference: bool = True,
) -> Decimal | None:
    """Resolve tax rate as a percentage (10 = 10%)."""
    rate = _rate_from_object(data, allow_inference=allow_inference)
    if rate is None or ocr_text is None or allow_inference:
        return rate
    from app.services.extraction.field_grounding_service import value_grounded_in_ocr

    token = str(rate).strip()
    if token and value_grounded_in_ocr(token, ocr_text, field_key="gst_rate"):
        return rate
    percent_token = f"{token}%"
    if value_grounded_in_ocr(percent_token, ocr_text, field_key="gst_rate"):
        return rate
    return None


def expected_gst_amount(subtotal: Decimal, rate_percent: Decimal) -> Decimal:
    return (subtotal * rate_percent / Decimal("100")).quantize(Decimal("0.01"))


def invoice_gst_rate_fraction(invoice: object) -> float | None:
    rate = resolve_gst_rate_percent(invoice)
    if rate is None:
        return None
    return float(rate / Decimal("100"))
