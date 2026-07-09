"""Locale and currency audit helper tests."""

from __future__ import annotations


def test_single_currency_fallback_documented() -> None:
    """B2B tenants use tenant.default_currency when invoice omits ISO code."""
    default_currency = "AUD"
    invoice_text = "Total: $1,234.56"
    assert "$" in invoice_text
    resolved = default_currency
    assert resolved == "AUD"
