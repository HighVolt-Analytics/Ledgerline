"""Tests for post-vision currency/total reconcile from local PDF text."""

from __future__ import annotations

from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice.vision_header_reconcile import (
    apply_vision_header_text_reconcile,
    prefer_grand_total_over_subtotal,
    reconcile_currency_from_text,
)
from app.tenant_ids import TESTING_TENANT_UUID


def test_rupee_overrides_wrong_aud() -> None:
    iso, symbol, reason = reconcile_currency_from_text(
        current_currency="AUD",
        text="TAX INVOICE\nTotal ₹9800.53\nMakeMyTrip (India)",
    )
    assert iso == "INR"
    assert symbol is None
    assert "override" in reason


def test_bare_dollar_clears_uncorroborated_aud() -> None:
    iso, symbol, reason = reconcile_currency_from_text(
        current_currency="AUD",
        text="Rosty.ai x LML Content Invoice\nTotal $1,399.00\n50% Advance $699.50",
    )
    assert iso == ""
    assert symbol == "$"
    assert "cleared" in reason


def test_bare_dollar_empty_stays_empty_with_symbol() -> None:
    iso, symbol, reason = reconcile_currency_from_text(
        current_currency="",
        text="Invoice\nTotal $100.00",
    )
    assert iso == ""
    assert symbol == "$"
    assert "ambiguous" in reason


def test_us_prefix_keeps_usd() -> None:
    iso, symbol, reason = reconcile_currency_from_text(
        current_currency="USD",
        text="MongoDB Limited\nTotal US$37.08",
    )
    assert iso == "USD"
    assert symbol is None
    assert "corroborated" in reason or "confirms" in reason or "ocr" in reason


def test_prefer_grand_total_over_subtotal_mongodb_style() -> None:
    text = (
        "server hour $32.25\n"
        "Subtotal $33.70\n"
        "Value-Added Tax $3.38\n"
        "Credits $0.00\n"
        "Total $37.08\n"
    )
    money, reason = prefer_grand_total_over_subtotal(Decimal("33.70"), text)
    assert money == Decimal("37.08")
    assert "upgraded" in reason


def test_apply_reconcile_updates_invoice() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        total=Decimal("9434.00"),
        extracted_fields={"currency": "AUD", "total": "9434.00"},
    )
    text = (
        "MakeMyTrip (India) Private Limited\n"
        "Subtotal ₹9434.00\n"
        "Total ₹9800.53\n"
    )
    detail = apply_vision_header_text_reconcile(inv, text)
    assert inv.currency == "INR"
    assert inv.total == Decimal("9800.53")
    assert (inv.extracted_fields or {}).get("currency") == "INR"
    assert detail["currency_after"] == "INR"
    assert "upgraded" in str(detail["total_reason"])
