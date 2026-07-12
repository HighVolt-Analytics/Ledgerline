"""Dedicated line-items shape gate tests (Sprint 0.6 / 0.19 / 0.20)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.citation_grounding_service import verify_and_apply_citations
from app.services.extraction.extraction_orchestrator import merge_extraction_sources
from app.services.extraction.line_items_parser import (
    document_has_product_table,
    document_has_qty_only_table,
    parse_qty_only_line_items_from_text,
)
from app.services.extraction.pdf_parser import parse_local_text
from app.schemas.llm_document import LlmDocumentResult

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _ocr(text: str) -> OcrArtifact:
    return OcrArtifact(text=text, sparse=False, text_length=len(text))


def test_di_empty_array_falls_through_to_qty_only() -> None:
    text = (_FIXTURES / "qty_only_table_ocr.txt").read_text(encoding="utf-8")
    parsed = parse_local_text(text)
    ocr = _ocr(text)
    ocr.payload_json = {"di_line_items": []}
    merged = merge_extraction_sources(parsed, ocr, dt_definition=None)
    assert len(merged.line_items or parse_qty_only_line_items_from_text(text)) >= 5


def test_di_missing_key_same_as_empty() -> None:
    text = (_FIXTURES / "qty_only_table_ocr.txt").read_text(encoding="utf-8")
    parsed = parse_local_text(text)
    ocr = _ocr(text)
    merged = merge_extraction_sources(parsed, ocr, dt_definition=None)
    assert document_has_qty_only_table(text, ocr.payload_json or {})


def test_qty_only_shape_uses_qty_only_prompt_path() -> None:
    text = (_FIXTURES / "delivery_challan_qty_table.txt").read_text(encoding="utf-8")
    assert document_has_qty_only_table(text, {})
    assert not document_has_product_table(text, {})


def test_totals_row_excluded_from_qty_only_rows() -> None:
    text = (_FIXTURES / "qty_only_table_ocr.txt").read_text(encoding="utf-8")
    rows = parse_qty_only_line_items_from_text(text)
    assert len(rows) == 5
    descriptions = [row.description for row in rows]
    assert not any((desc or "").upper().startswith("TOTAL") for desc in descriptions)


def test_multipage_table_page1_rows_extracted() -> None:
    text = (Path(__file__).parent / "fixtures" / "golden" / "multipage_table_p1" / "input.txt").read_text(
        encoding="utf-8"
    )
    parsed = parse_local_text(text)
    merged = merge_extraction_sources(parsed, _ocr(text), dt_definition=None)
    assert len(merged.line_items or []) >= 2


def test_multipage_continuation_page2_rows() -> None:
    text = (Path(__file__).parent / "fixtures" / "golden" / "multipage_table_p2" / "input.txt").read_text(
        encoding="utf-8"
    )
    parsed = parse_local_text(text)
    merged = merge_extraction_sources(parsed, _ocr(text), dt_definition=None)
    assert len(merged.line_items or []) >= 1


def test_nontabular_invoice_empty_line_items_no_error() -> None:
    text = (Path(__file__).parent / "fixtures" / "golden" / "nontabular_lumpsum" / "input.txt").read_text(
        encoding="utf-8"
    )
    assert not document_has_qty_only_table(text, {})
    assert not document_has_product_table(text, {})
    parsed = parse_local_text(text)
    merged = merge_extraction_sources(parsed, _ocr(text), dt_definition=None)
    assert merged.line_items == []


def test_nontabular_no_false_citation_failure_on_line_items() -> None:
    text = (Path(__file__).parent / "fixtures" / "golden" / "nontabular_lumpsum" / "input.txt").read_text(
        encoding="utf-8"
    )
    llm = LlmDocumentResult(
        vendor="ACME SUBSCRIPTION LTD",
        invoice_no="SUB-2025-001",
        field_citations={},
    )
    _, results = verify_and_apply_citations(llm, _ocr(text), field_keys=["vendor", "invoice_no"])
    failed = [row.field_key for row in results if not row.verified]
    assert "line_items" not in failed


def test_garbage_di_line_items_falls_through_to_qty_only() -> None:
    text = (_FIXTURES / "qty_only_table_ocr.txt").read_text(encoding="utf-8")
    parsed = parse_local_text(text)
    ocr = _ocr(text)
    ocr.payload_json = {
        "di_line_items": [{"description": "PACKING LIST HEADER", "qty": None}],
    }
    assert document_has_qty_only_table(text, ocr.payload_json)
    merged = merge_extraction_sources(parsed, ocr, dt_definition=None)
    assert len(merged.line_items or []) >= 5


def test_money_table_line_items_merged_when_llm_empty() -> None:
    from app.services.invoice.invoice_data import InvoiceData

    parsed = InvoiceData(vendor="ACME", line_items=[])
    ocr = _ocr(
        "DESCRIPTION QTY UNIT PRICE AMOUNT\n"
        "Widget A 2 10.00 20.00\n"
        "Widget B 1 5.00 5.00\n"
    )
    ocr.payload_json = {
        "table_line_items": [
            {"description": "Widget A", "qty": "2", "unit_price": "10.00", "amount": "20.00"},
            {"description": "Widget B", "qty": "1", "unit_price": "5.00", "amount": "5.00"},
        ]
    }
    merged = merge_extraction_sources(parsed, ocr, dt_definition=None)
    assert len(merged.line_items) == 2
    assert merged.line_items[0].amount == Decimal("20.00")


def test_single_row_money_table_detected() -> None:
    text = "DESCRIPTION QTY UNIT PRICE AMOUNT\nWidget A 2 10.00 20.00\n"
    assert document_has_product_table(text, {})
    parsed = parse_local_text(text)
    merged = merge_extraction_sources(parsed, _ocr(text), dt_definition=None)
    assert len(merged.line_items) == 1


def test_di_money_rows_block_qty_only_shape_even_if_table_longer() -> None:
    """Longer OCR qty bleed must not flip shape gate when DI already has money rows."""
    from app.services.extraction.line_items_parser import resolve_line_items_for_strategy

    payload = {
        "di_line_items": [
            {
                "description": "Platform subscription",
                "qty": "1",
                "unit_price": "40.00",
                "amount": "40.00",
            },
            {
                "description": "Support hours",
                "qty": "2",
                "unit_price": "2.515",
                "amount": "5.03",
            },
        ],
        "table_line_items": [
            {"description": "Prinsengracht", "qty": "769"},
            {"description": "$45.03 USD due May 1,", "qty": "2026"},
            {"description": "Page 1 of", "qty": "2"},
            {"description": "Page 2 of", "qty": "2"},
            {"description": "Mystery junk", "qty": "9"},
        ],
    }
    assert not document_has_qty_only_table("Prinsengracht 769\nPage 1 of 2", payload)
    resolved = resolve_line_items_for_strategy(
        payload,
        layout_mode="gap_fill",
        allow_qty_only=True,
    )
    descriptions = [(row.description or "") for row in resolved]
    assert len(resolved) == 2
    assert any("Platform" in desc for desc in descriptions)
    assert not any("Prinsengracht" in desc for desc in descriptions)
    assert not any("Page" in desc for desc in descriptions)
