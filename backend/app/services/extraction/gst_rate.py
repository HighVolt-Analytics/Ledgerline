"""Resolve GST/tax rate from extracted OCR fields or inferred amounts."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.invoice.invoice_data import InvoiceData

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
    return value.quantize(Decimal("0.01"))


def _rate_from_object(obj: object) -> Decimal | None:
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

    subtotal = getattr(obj, "subtotal", None)
    gst = getattr(obj, "gst", None)
    if subtotal is not None and gst is not None and subtotal > 0:
        return ((gst / subtotal) * Decimal("100")).quantize(Decimal("0.01"))
    return None


def resolve_gst_rate_percent(data: InvoiceData | object) -> Decimal | None:
    """Resolve tax rate as a percentage (10 = 10%)."""
    if isinstance(data, InvoiceData):
        return _rate_from_object(data)
    return _rate_from_object(data)


def expected_gst_amount(subtotal: Decimal, rate_percent: Decimal) -> Decimal:
    return (subtotal * rate_percent / Decimal("100")).quantize(Decimal("0.01"))


def invoice_gst_rate_fraction(invoice: object) -> float | None:
    rate = resolve_gst_rate_percent(invoice)
    if rate is None:
        return None
    return float(rate / Decimal("100"))
