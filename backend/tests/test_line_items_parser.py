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
