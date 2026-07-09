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


def test_sanitize_removes_phone_fragment_rows() -> None:
    items = [
        ParsedLineItem(description="Tel No:+91", qty=Decimal("22"), unit_price=Decimal("2889"), amount=Decimal("6699")),
        ParsedLineItem(description="TAMOXILON 20", qty=Decimal("1"), unit_price=Decimal("1.60"), amount=Decimal("16000")),
    ]
    cleaned = sanitize_line_items(items)
    assert len(cleaned) == 1
    assert cleaned[0].description == "TAMOXILON 20"


def test_sanitize_keeps_qty_only_rows_when_allowed() -> None:
    items = [
        ParsedLineItem(description="CPU CHIPS 14 Gen I3 14100", qty=Decimal("150"), unit_price=None, amount=None),
    ]
    cleaned = sanitize_line_items(items, allow_qty_only=True)
    assert len(cleaned) == 1
    assert cleaned[0].qty == Decimal("150")


def test_sanitize_drops_qty_only_rows_without_flag() -> None:
    items = [
        ParsedLineItem(description="CPU CHIPS 14 Gen I3 14100", qty=Decimal("150"), unit_price=None, amount=None),
    ]
    cleaned = sanitize_line_items(items, allow_qty_only=False)
    assert cleaned == []


def test_sanitize_keeps_gst_in_product_description() -> None:
    items = [
        ParsedLineItem(
            description="GST consulting services",
            qty=Decimal("1"),
            unit_price=Decimal("350"),
            amount=Decimal("350"),
        ),
    ]
    cleaned = sanitize_line_items(items)
    assert len(cleaned) == 1
    assert cleaned[0].description == "GST consulting services"


def test_has_trusted_line_items_requires_money_fields() -> None:
    from app.services.extraction.line_item_skip_patterns import has_trusted_line_items
    from app.services.invoice.invoice_data import ParsedLineItem

    assert not has_trusted_line_items(
        [ParsedLineItem(description="Widget", qty=Decimal("2"), unit_price=None, amount=None)]
    )
    assert has_trusted_line_items(
        [ParsedLineItem(description="Widget", qty=Decimal("2"), unit_price=Decimal("50"), amount=None)]
    )
    assert has_trusted_line_items(
        [ParsedLineItem(description="Widget", qty=None, unit_price=None, amount=Decimal("100"))]
    )


def test_sanitize_removes_vendor_and_so_reference_duplicates() -> None:
    items = [
        ParsedLineItem(description="High Volt Analytics Pty Ltd", qty=Decimal("1"), amount=Decimal("100")),
        ParsedLineItem(description="Widget", qty=Decimal("2"), unit_price=Decimal("50"), amount=Decimal("100")),
    ]
    cleaned = sanitize_line_items(
        items,
        vendor="High Volt Analytics Pty Ltd",
        so_reference="SO-9001",
    )
    assert len(cleaned) == 1
    assert cleaned[0].description == "Widget"
