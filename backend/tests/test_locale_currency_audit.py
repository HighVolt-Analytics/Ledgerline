"""Locale and currency audit helper tests."""

from __future__ import annotations


def test_bare_dollar_stays_ambiguous_not_usd_or_tenant_default() -> None:
    """Bare $ must not invent USD (or tenant AUD/SGD) — leave ISO empty, keep glyph."""
    from app.services.shared.currency import resolve_currency_from_ocr

    invoice_text = "Total: $1,234.56"
    assert "$" in invoice_text
    iso, symbol = resolve_currency_from_ocr(invoice_text)
    assert iso == ""
    assert symbol == "$"
