from decimal import Decimal

from app.services.extraction.line_item_header_vocab import vertical_header_role
from app.services.extraction.line_items_fallback_service import apply_line_items_fallback
from app.services.extraction.line_items_parser import (
    document_has_qty_only_table,
    parse_line_items_from_text,
    parse_vertical_line_items_from_text,
)
from app.services.invoice.invoice_data import InvoiceData

ZUVAN_TEXT = """
ZUVAN ENERGY PRIVATE LIMITED
Site Office: Plot No.4, Gadivemula Mandal, Gani, Kurnool, Andhra Pradesh - 51810
INVOICE
SI.No
Description
HSN Code
Qty in units
Price per
VER (USD)
Amount in USD
1
Sale of VERs
49070090
100000
0.70
$70,000
Total Amount:
$70,000
""".strip()


def test_zuvan_vertical_headers() -> None:
    headers = [
        "SI.No",
        "Description",
        "HSN Code",
        "Qty in units",
        "Price per",
        "VER (USD)",
        "Amount in USD",
    ]
    assert [vertical_header_role(h) for h in headers] == [
        "skip",
        "description",
        "skip",
        "qty",
        "unit_price",
        None,
        "amount",
    ]


def test_zuvan_vertical_line_parse() -> None:
    rows = parse_vertical_line_items_from_text(ZUVAN_TEXT)
    assert len(rows) == 1
    assert "VER" in (rows[0].description or "").upper()
    assert rows[0].qty == Decimal("100000")
    assert rows[0].unit_price == Decimal("0.70")
    assert rows[0].amount == Decimal("70000")


def test_zuvan_fallback_rejects_address_qty_bleed() -> None:
    assert document_has_qty_only_table(ZUVAN_TEXT, {}) is False
    updated, tier = apply_line_items_fallback(
        InvoiceData(document_text=ZUVAN_TEXT, total=Decimal("70000")),
        ocr_text=ZUVAN_TEXT,
    )
    assert tier == "fallback_structured"
    assert len(updated.line_items) == 1
    assert updated.line_items[0].amount == Decimal("70000")
    assert not any("Site Office" in (r.description or "") for r in updated.line_items)
    assert not any((r.description or "").startswith("PH:") for r in updated.line_items)


def test_parse_line_items_from_text_zuvan() -> None:
    rows = parse_line_items_from_text(ZUVAN_TEXT)
    assert len(rows) == 1
    assert rows[0].amount == Decimal("70000")
