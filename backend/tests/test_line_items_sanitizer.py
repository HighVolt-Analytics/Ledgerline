"""Tests for post-merge line item sanitization."""

from decimal import Decimal

from app.services.extraction.line_items_sanitizer import sanitize_line_items
from app.services.invoice.invoice_data import ParsedLineItem


def test_sanitize_removes_label_value_header_rows_with_money() -> None:
    items = [
        ParsedLineItem(
            description="Ship To: Acme Corp",
            qty=Decimal("1"),
            unit_price=Decimal("10"),
            amount=Decimal("10"),
        ),
        ParsedLineItem(
            description="Invoice Date: 01/01/2026",
            qty=None,
            unit_price=None,
            amount=Decimal("100"),
        ),
        ParsedLineItem(
            description="Widget assembly",
            qty=Decimal("2"),
            unit_price=Decimal("50"),
            amount=Decimal("100"),
        ),
    ]
    cleaned = sanitize_line_items(items)
    assert len(cleaned) == 1
    assert cleaned[0].description == "Widget assembly"


def test_sanitize_removes_bank_and_address_bleed() -> None:
    items = [
        ParsedLineItem(
            description="217 Henderson Road, Singapore 159555",
            qty=Decimal("159555"),
            amount=Decimal("1"),
        ),
        ParsedLineItem(
            description="Bank Details BSB 062-000",
            qty=None,
            amount=Decimal("500"),
        ),
        ParsedLineItem(
            description="Consulting hours",
            qty=Decimal("5"),
            unit_price=Decimal("100"),
            amount=Decimal("500"),
        ),
    ]
    cleaned = sanitize_line_items(items)
    assert len(cleaned) == 1
    assert cleaned[0].description == "Consulting hours"


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


def test_sanitize_drops_qty_only_bleed_when_money_rows_present() -> None:
    """Weaviate-style: DI money rows + regex address/page/due bleed must not survive."""
    items = [
        ParsedLineItem(
            description="Minimum amount\nApr 1-Apr 30, 2026",
            qty=Decimal("1"),
            unit_price=Decimal("44.61"),
            amount=Decimal("44.61"),
            source="fused",
        ),
        ParsedLineItem(
            description="Flex Shared - Storage GBs (backups)",
            qty=Decimal("1"),
            unit_price=Decimal("0.02"),
            amount=Decimal("0.02"),
            source="fused",
        ),
        ParsedLineItem(description="Prinsengracht", qty=Decimal("769"), source="regex"),
        ParsedLineItem(description="$45.03 USD due May 1,", qty=Decimal("2026"), source="regex"),
        ParsedLineItem(description="Page 1 of", qty=Decimal("2"), source="regex"),
        ParsedLineItem(description="Page 2 of", qty=Decimal("2"), source="regex"),
    ]
    cleaned = sanitize_line_items(items, allow_qty_only=True)
    assert len(cleaned) == 2
    assert all(item.amount is not None for item in cleaned)
    assert all("Page" not in (item.description or "") for item in cleaned)
    assert all("Prinsengracht" not in (item.description or "") for item in cleaned)
    assert all("due" not in (item.description or "").lower() for item in cleaned)


def test_sanitize_keeps_qty_only_when_no_money_rows() -> None:
    items = [
        ParsedLineItem(description="CPU CHIPS 14 Gen I3 14100", qty=Decimal("150"), source="regex"),
    ]
    cleaned = sanitize_line_items(items, allow_qty_only=True)
    assert len(cleaned) == 1


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
