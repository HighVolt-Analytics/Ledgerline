"""Tests for line item merge and enrichment helpers."""

from decimal import Decimal

from app.services.extraction.line_items_parser import (
    enrich_line_items_from_text,
    enrich_parsed_line_items,
    merge_line_item_lists,
)
from app.services.invoice.invoice_data import ParsedLineItem


def test_merge_line_item_lists_fills_missing_prices() -> None:
    primary = [
        ParsedLineItem(description="Catering package", qty=Decimal("10"), unit_price=None, amount=None),
    ]
    secondary = [
        ParsedLineItem(
            description="Catering package",
            qty=Decimal("10"),
            unit_price=Decimal("50"),
            amount=Decimal("500"),
        ),
    ]
    merged = merge_line_item_lists(primary, secondary)
    assert len(merged) == 1
    assert merged[0].unit_price == Decimal("50")
    assert merged[0].amount == Decimal("500")


def test_enrich_line_items_from_text_fills_missing_prices() -> None:
    items = [
        ParsedLineItem(description="Western Digital 4TB HDD", qty=Decimal("80"), unit_price=None, amount=None),
    ]
    text = "Western Digital 4TB HDD    80    145.00    11600.00"
    enriched = enrich_line_items_from_text(items, text)
    assert enriched[0].unit_price == Decimal("145")
    assert enriched[0].amount == Decimal("11600")


def test_enrich_parsed_line_items_derives_amount() -> None:
    items = enrich_parsed_line_items(
        [ParsedLineItem(description="Widget", qty=Decimal("4"), unit_price=Decimal("25"), amount=None)]
    )
    assert items[0].amount == Decimal("100")


def test_enrich_line_items_from_text_skips_pallet_rows() -> None:
    items = [
        ParsedLineItem(description="TOTAL NO. OF PALLET :", qty=Decimal("1"), unit_price=Decimal("1195"), amount=Decimal("34410.95")),
        ParsedLineItem(description="Sandisk 4TB SSD", qty=Decimal("15"), unit_price=None, amount=None),
    ]
    text = "Sandisk 4TB SSD 15 1195.00 17925.00"
    enriched = enrich_line_items_from_text(items, text)
    assert len(enriched) == 1
    assert enriched[0].description == "Sandisk 4TB SSD"
    assert enriched[0].amount == Decimal("17925")


def test_enrich_line_items_from_text_parses_sgd_rows() -> None:
    items = [
        ParsedLineItem(description="Consulting retainer", qty=Decimal("1"), unit_price=None, amount=None),
    ]
    text = "Consulting retainer 1 SGD 500.00 SGD 500.00"
    enriched = enrich_line_items_from_text(items, text)
    assert enriched[0].unit_price == Decimal("500")
    assert enriched[0].amount == Decimal("500")


def test_parse_line_items_handles_month_year_in_description() -> None:
    from app.services.extraction.line_items_parser import parse_line_items_from_text

    text = """
DESCRIPTION QTY UNIT PRICE GST AMOUNT
EC2 Compute - May 2026 1 $2,450.00 $245.00 $2,695.00
S3 Storage & Data Transfer 1 $380.00 $38.00 $418.00
"""
    items = parse_line_items_from_text(text)
    assert len(items) == 2
    assert items[0].description == "EC2 Compute - May 2026"
    assert items[0].qty == Decimal("1")
    assert items[0].unit_price == Decimal("2450.00")
    assert items[0].amount == Decimal("2695.00")
    assert items[0].source == "regex"
    assert items[1].description == "S3 Storage & Data Transfer"
    assert items[1].qty == Decimal("1")


def test_repair_year_misplaced_as_qty() -> None:
    from app.services.extraction.line_items_parser import enrich_parsed_line_items

    items = enrich_parsed_line_items(
        [
            ParsedLineItem(
                description="EC2 Compute - May",
                qty=Decimal("2026"),
                unit_price=Decimal("1"),
                amount=Decimal("1"),
            ),
            ParsedLineItem(
                description="EC2 Compute - May 2026",
                qty=Decimal("1"),
                unit_price=Decimal("2450"),
                amount=Decimal("2695"),
            ),
        ]
    )
    assert len(items) == 1
    assert items[0].description == "EC2 Compute - May 2026"
    assert items[0].qty == Decimal("1")
    assert items[0].unit_price == Decimal("2450")


def test_enrich_line_items_from_text_parses_month_year_description() -> None:
    items = [
        ParsedLineItem(description="EC2 Compute - May 2026", qty=Decimal("1"), unit_price=None, amount=None),
    ]
    text = "EC2 Compute - May 2026 1 $2,450.00 $245.00 $2,695.00"
    enriched = enrich_line_items_from_text(items, text)
    assert enriched[0].unit_price == Decimal("2450")
    assert enriched[0].amount == Decimal("2695")


def test_document_has_qty_only_table_on_spectra_fixture() -> None:
    from pathlib import Path

    from app.services.extraction.line_items_parser import (
        document_has_qty_only_table,
        parse_qty_only_line_items_from_text,
    )

    text = Path("tests/fixtures/qty_only_table_ocr.txt").read_text(encoding="utf-8")
    assert document_has_qty_only_table(text, {})
    items = parse_qty_only_line_items_from_text(text)
    assert len(items) == 5
    assert items[0].qty == Decimal("150")
    assert "CPU CHIPS 14 Gen I3 14100" in items[0].description


def test_document_has_qty_only_table_on_delivery_challan_fixture() -> None:
    from pathlib import Path

    from app.services.extraction.line_items_parser import document_has_qty_only_table

    text = Path("tests/fixtures/delivery_challan_qty_table.txt").read_text(encoding="utf-8")
    assert document_has_qty_only_table(text, {})


def test_document_has_qty_only_table_false_when_money_columns_present() -> None:
    from app.services.extraction.line_items_parser import document_has_qty_only_table

    text = """
DESCRIPTION QTY UNIT PRICE AMOUNT
Widget A 2 10.00 20.00
"""
    assert not document_has_qty_only_table(text, {})


def test_build_line_items_presentation_prompt_qty_only_mode() -> None:
    from app.services.extraction.line_items_parser import build_line_items_presentation_prompt

    lines = build_line_items_presentation_prompt(
        di_rows_present=False,
        ocr_table_present=False,
        qty_only_table_present=True,
    )
    joined = "\n".join(lines)
    assert "QTY-ONLY TABLE" in joined
    assert "TOTALS" in joined


def test_line_item_thresholds_default_matches_existing_fixture() -> None:
    from app.services.extraction.line_items_parser import parse_line_items_from_text

    text = """
DESCRIPTION QTY UNIT PRICE GST AMOUNT
EC2 Compute - May 2026 1 $2,450.00 $245.00 $2,695.00
"""
    items = parse_line_items_from_text(text)
    assert len(items) == 1
    assert items[0].unit_price == Decimal("2450.00")


def test_line_item_thresholds_max_qty_affects_row_score() -> None:
    from app.services.extraction.line_item_parsing_config import LineItemParsingThresholds
    from app.services.extraction.line_items_parser import _line_item_row_score

    item = ParsedLineItem(description="Bulk order", qty=Decimal("800"), unit_price=Decimal("10"), amount=Decimal("8000"))
    strict = LineItemParsingThresholds(max_plausible_qty=Decimal("500"))
    loose = LineItemParsingThresholds(max_plausible_qty=Decimal("10000"))
    assert _line_item_row_score(item, thresholds=strict) < _line_item_row_score(item, thresholds=loose)


def test_parse_line_items_from_di_items_sets_source_di() -> None:
    from types import SimpleNamespace

    from app.services.extraction.line_items_parser import parse_line_items_from_di_items

    def field(val: str) -> SimpleNamespace:
        return SimpleNamespace(value_string=val)

    row = SimpleNamespace(
        value_object={
            "Description": field("Widget"),
            "Quantity": field("2"),
            "UnitPrice": field("10.00"),
            "Amount": field("20.00"),
        }
    )
    items = parse_line_items_from_di_items(SimpleNamespace(value_array=[row]))
    assert len(items) == 1
    assert items[0].source == "di"
    assert items[0].amount == Decimal("20")


def test_parse_line_items_from_table_grid_sets_source_table() -> None:
    from app.services.extraction.layout_field_extractor import parse_line_items_from_table_grid

    rows = [
        ["Description", "Qty", "Unit Price", "Amount"],
        ["Widget A", "2", "10.00", "20.00"],
    ]
    items = parse_line_items_from_table_grid(rows)
    assert len(items) == 1
    assert items[0].source == "table"
    assert items[0].description == "Widget A"


def test_serialize_line_items_round_trips_tax_amount() -> None:
    from app.services.extraction.line_items_parser import deserialize_line_items, serialize_line_items

    items = [
        ParsedLineItem(
            description="EC2 Compute - May 2026",
            qty=Decimal("1"),
            unit_price=Decimal("2450.00"),
            tax_amount=Decimal("245.00"),
            amount=Decimal("2695.00"),
            source="regex",
        )
    ]
    payload = serialize_line_items(items)
    restored = deserialize_line_items(payload)
    assert len(restored) == 1
    assert restored[0].tax_amount == Decimal("245.00")
    assert restored[0].amount == Decimal("2695.00")
