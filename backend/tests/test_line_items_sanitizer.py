"""Tests for post-merge line item sanitization."""

from decimal import Decimal

from app.services.extraction.line_items_sanitizer import sanitize_line_items
from app.services.invoice.invoice_data import ParsedLineItem


def test_sanitize_removes_delivery_note_metadata_rows() -> None:
    items = [
        ParsedLineItem(description="Customer:", qty=Decimal("10"), unit_price=None, amount=None),
        ParsedLineItem(description="Customer:", qty=None, unit_price=None, amount=None),
        ParsedLineItem(description="Shipped Qty:", qty=None, unit_price=None, amount=None),
        ParsedLineItem(description="Ship Date:", qty=None, unit_price=None, amount=None),
        ParsedLineItem(
            description="Widget assembly",
            qty=Decimal("2"),
            unit_price=Decimal("50"),
            amount=Decimal("100"),
        ),
    ]
    cleaned = sanitize_line_items(
        items,
        extracted_fields={"customer": "Harbour View Hotel"},
        vendor="High Volt Analytics Pty Ltd",
    )
    assert len(cleaned) == 1
    assert cleaned[0].description == "Widget assembly"


def test_sanitize_removes_summary_rows() -> None:
    items = [
        ParsedLineItem(description="Sub Total", qty=None, unit_price=None, amount=Decimal("500")),
        ParsedLineItem(description="SEO Services", qty=Decimal("1"), unit_price=Decimal("35000"), amount=Decimal("35000")),
    ]
    cleaned = sanitize_line_items(items)
    assert len(cleaned) == 1
    assert cleaned[0].description == "SEO Services"
