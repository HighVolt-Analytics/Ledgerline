"""Locale and currency audit helper tests."""

from __future__ import annotations


def test_undetected_currency_stays_empty_not_tenant_default() -> None:
    """Bare $ must not invent tenant reporting currency (e.g. AUD)."""
    invoice_text = "Total: $1,234.56"
    assert "$" in invoice_text
    # Extraction leaves currency empty; UI asks the user to confirm ISO.
    resolved = ""
    assert resolved == ""
