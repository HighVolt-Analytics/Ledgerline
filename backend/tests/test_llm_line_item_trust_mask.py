"""Per-row LLM line-item trust mask tests."""

from decimal import Decimal

from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.extraction_orchestrator import (
    _llm_line_items_fully_trusted,
    _llm_line_items_trust_mask,
    merge_extraction_sources,
)
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem


def test_trust_mask_partial_row() -> None:
    items = [
        ParsedLineItem(description="A", qty=Decimal("1"), unit_price=Decimal("10"), amount=Decimal("10")),
        ParsedLineItem(description="B", qty=Decimal("2"), unit_price=None, amount=Decimal("20")),
        ParsedLineItem(description="C", qty=Decimal("3"), unit_price=Decimal("5"), amount=Decimal("15")),
    ]
    mask = _llm_line_items_trust_mask(items)
    assert mask == [True, False, True]
    assert not _llm_line_items_fully_trusted(items, None)


def test_merge_partial_llm_backfills_from_table() -> None:
    table_rows = [
        {"description": "Widget A", "qty": "2", "unit_price": "10", "amount": "20"},
        {"description": "Widget B", "qty": "1", "unit_price": "5", "amount": "5"},
        {"description": "Widget C", "qty": "3", "unit_price": "2", "amount": "6"},
        {"description": "Widget D", "qty": "1", "unit_price": "8", "amount": "8"},
    ]
    text = (
        "DESCRIPTION QTY UNIT PRICE AMOUNT\n"
        "Widget A 2 10.00 20.00\n"
        "Widget B 1 5.00 5.00\n"
        "Widget C 3 2.00 6.00\n"
        "Widget D 1 8.00 8.00\n"
    )
    parsed = InvoiceData(
        line_items=[
            ParsedLineItem(description="Widget A", qty=Decimal("2"), unit_price=Decimal("10"), amount=Decimal("20")),
            ParsedLineItem(description="Widget B", qty=Decimal("1"), unit_price=None, amount=Decimal("5")),
            ParsedLineItem(description="Widget C", qty=Decimal("3"), unit_price=Decimal("2"), amount=Decimal("6")),
            ParsedLineItem(description="Widget D", qty=Decimal("1"), unit_price=Decimal("8"), amount=Decimal("8")),
        ],
        raw_fields={"_line_items_confidence": 0.5},
    )
    ocr = OcrArtifact(success=True, text=text, text_length=len(text), payload_json={"table_line_items": table_rows})
    merged = merge_extraction_sources(parsed, ocr)
    assert len(merged.line_items) == 4
    by_desc = {item.description: item for item in merged.line_items}
    assert by_desc["Widget A"].unit_price == Decimal("10")
    assert by_desc["Widget B"].unit_price == Decimal("5")


def test_merge_keeps_all_llm_when_fully_trusted() -> None:
    parsed = InvoiceData(
        line_items=[
            ParsedLineItem(
                description="Catering package",
                qty=Decimal("10"),
                unit_price=Decimal("50"),
                amount=Decimal("500"),
            ),
        ],
        raw_fields={"_line_items_confidence": 0.95},
    )
    ocr = OcrArtifact(
        success=True,
        text="Wrong Product 99 1.00 99.00\n",
        text_length=28,
        payload_json={
            "table_line_items": [
                {
                    "description": "Wrong Product",
                    "qty": "99",
                    "unit_price": "1",
                    "amount": "99",
                }
            ]
        },
    )
    merged = merge_extraction_sources(parsed, ocr)
    assert merged.line_items[0].description == "Catering package"
