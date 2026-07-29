"""Locale and currency audit helper tests."""

from __future__ import annotations


def test_bare_dollar_defaults_to_usd_not_tenant_default() -> None:
    """Bare $ maps to USD rather than tenant reporting currency (e.g. AUD)."""
    from app.services.shared.currency import resolve_currency_from_ocr

    invoice_text = "Total: $1,234.56"
    assert "$" in invoice_text
    iso, symbol = resolve_currency_from_ocr(invoice_text)
    assert iso == "USD"
    assert symbol is None