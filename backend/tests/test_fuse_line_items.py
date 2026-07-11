"""Parity tests for feature-flagged fuse_line_items."""

from decimal import Decimal
from unittest.mock import patch

import pytest

from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.extraction_orchestrator import (
    _collect_line_item_fusion_sources,
    _merge_line_items_from_sources,
    merge_extraction_sources,
)
from app.services.extraction.field_fusion_engine import fuse_line_items
from app.services.extraction.line_items_parser import merge_line_item_lists
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem


def _product_table_fixture() -> tuple[InvoiceData, OcrArtifact]:
    table_rows = [
        {"description": "Widget A", "qty": "2", "unit_price": "10", "amount": "20"},
        {"description": "Widget B", "qty": "1", "unit_price": "5", "amount": "5"},
    ]
    text = (
        "DESCRIPTION QTY UNIT PRICE AMOUNT\n"
        "Widget A 2 10.00 20.00\n"
        "Widget B 1 5.00 5.00\n"
    )
    parsed = InvoiceData(
        line_items=[
            ParsedLineItem(
                description="Widget A",
                qty=Decimal("2"),
                unit_price=Decimal("10"),
                amount=Decimal("20"),
            ),
        ]
    )
    ocr = OcrArtifact(success=True, text=text, text_length=len(text), payload_json={"table_line_items": table_rows})
    return parsed, ocr


def test_merge_line_item_lists_sets_fused_provenance() -> None:
    primary = [
        ParsedLineItem(
            description="Catering package",
            qty=Decimal("10"),
            unit_price=None,
            amount=None,
            source="llm",
        ),
    ]
    secondary = [
        ParsedLineItem(
            description="Catering package",
            qty=Decimal("10"),
            unit_price=Decimal("50"),
            amount=Decimal("500"),
            source="table",
        ),
    ]
    merged = merge_line_item_lists(primary, secondary)
    assert len(merged) == 1
    assert merged[0].source == "fused"
    assert merged[0].fused_from == ["llm", "table"]


def test_fuse_line_items_merges_priority_sources() -> None:
    llm = [ParsedLineItem(description="A", qty=Decimal("1"), unit_price=None, amount=None)]
    layout = [
        ParsedLineItem(description="A", qty=Decimal("1"), unit_price=Decimal("5"), amount=Decimal("5")),
    ]
    fused = fuse_line_items({"llm": llm, "layout": layout})
    assert fused[0].unit_price == Decimal("5")


@pytest.mark.parametrize("use_fusion", [False, True])
def test_fusion_path_equal_or_better_than_legacy(use_fusion: bool) -> None:
    parsed, ocr = _product_table_fixture()
    text = ocr.text or ""
    payload = dict(ocr.payload_json or {})

    legacy = _merge_line_items_from_sources(parsed, text, payload)
    sources = _collect_line_item_fusion_sources(parsed, text, payload)
    fused = fuse_line_items(sources)

    assert len(fused) >= len(legacy)
    for legacy_row in legacy:
        match = next(
            (row for row in fused if (row.description or "").lower() == (legacy_row.description or "").lower()),
            None,
        )
        assert match is not None
        if legacy_row.amount is not None:
            assert match.amount == legacy_row.amount

    with patch("app.config.get_settings") as mock_settings, patch(
        "app.config.flag_enabled_for_dt", return_value=use_fusion
    ):
        mock_settings.return_value.use_field_fusion = use_fusion
        merged = merge_extraction_sources(parsed, ocr)
    assert len(merged.line_items) >= 1
