"""Layout table grid fallback when OCR whitespace is normalized."""

from decimal import Decimal

from app.services.extraction.line_items_parser import (
    _parse_table_row_tail,
    parse_line_items_from_layout_grids,
    parse_line_items_from_text,
)
from app.services.invoice.invoice_data import ParsedLineItem


def test_layout_grid_fallback_parses_normalized_whitespace_text() -> None:
    text = "Widget A 2 10.00 20.00"
    payload = {
        "layout_table_grids": [
            [
                ["Description", "Qty", "Unit Price", "Amount"],
                ["Widget A", "2", "10.00", "20.00"],
            ]
        ]
    }
    items = parse_line_items_from_text(text, payload)
    assert len(items) == 1
    assert items[0].description == "Widget A"
    assert items[0].qty == Decimal("2")
    assert items[0].unit_price == Decimal("10")
    assert items[0].amount == Decimal("20")


def test_whitespace_split_degrades_without_grid() -> None:
    line = "Widget A 2 10.00 20.00"
    parsed = _parse_table_row_tail(line)
    # Single-space columns cannot split; tail regex may still match trailing money.
    if parsed is not None:
        assert parsed.description
    else:
        assert parse_line_items_from_text(line, {}) == []


def test_parse_line_items_from_layout_grids_direct() -> None:
    payload = {
        "layout_table_grids": [
            [
                ["Item", "Qty", "Rate", "Total"],
                ["Service fee", "1", "100.00", "100.00"],
            ]
        ]
    }
    items = parse_line_items_from_layout_grids(payload)
    assert len(items) == 1
    assert items[0].amount == Decimal("100")
