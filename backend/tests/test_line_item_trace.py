"""Tests for structured line-item extraction trace."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.extraction_orchestrator import merge_extraction_sources
from app.services.extraction.line_item_trace import LineItemTrace
from app.services.extraction.line_items_sanitizer import sanitize_line_items
from app.services.extraction.pdf_parser import parse_local_text
from app.services.invoice.invoice_data import ParsedLineItem


def _ocr(text: str, payload: dict | None = None) -> OcrArtifact:
    return OcrArtifact(text=text, sparse=False, text_length=len(text), payload_json=payload or {})


def test_line_item_trace_fixture_e() -> None:
    text = (
        "217 Henderson Road, #03-10, Singapore 159555\n"
        "INVOICE NO. : 260371344/\n"
        "CPU CHIPS 14 Gen 13 14100 | CHINA | 9.70 | 10.60 | 1 | 81 X 61 X 97\n"
        "DOCUMENTARY CREDIT NUMBER: 308526022170 DATED 260316\n"
    )
    payload = {
        "table_line_items": [
            {
                "qty": "150",
                "description": "CPU CHIPS 14 Gen 13 14100 | CHINA | 9.70 | 10.60 | 1 | 81 X 61 X 97",
            }
        ]
    }
    parsed = replace(
        parse_local_text(text),
        line_items=[
            ParsedLineItem(
                description="217 Henderson Road, #03-10, Singapore 159555",
                qty=Decimal("159555"),
                source="llm",
            ),
            ParsedLineItem(
                description="CPU CHIPS 14 Gen 13 14100 | CHINA | 9.70 | 10.60 | 1 | 81 X 61 X 97",
                qty=Decimal("1"),
                source="llm",
            ),
            ParsedLineItem(
                description="DOCUMENTARY CREDIT NUMBER: 308526022170 DATED 260316",
                qty=Decimal("260316"),
                source="llm",
            ),
        ],
    )
    trace = LineItemTrace()
    merged = merge_extraction_sources(parsed, _ocr(text, payload), trace=trace)
    assert len(merged.line_items or []) == 1
    assert "CPU CHIPS" in (merged.line_items[0].description or "")

    entries = trace.to_dict()
    dropped_reasons = {
        entry["reason"]
        for entry in entries
        if entry["action"] == "dropped"
    }
    assert "reference_block" in dropped_reasons

    kept_rows = [
        entry["row_key"]
        for entry in entries
        if entry["action"] == "kept" and "cpu chips" in entry["row_key"]
    ]
    assert kept_rows


def test_sanitize_line_items_trace_records_drops() -> None:
    trace = LineItemTrace()
    items = [
        ParsedLineItem(description="217 Henderson Road, Singapore 159555", qty=Decimal("159555")),
        ParsedLineItem(
            description="CPU CHIPS 14 Gen 13 14100",
            qty=Decimal("150"),
            amount=Decimal("100"),
        ),
    ]
    cleaned = sanitize_line_items(items, trace=trace)
    assert len(cleaned) == 1
    reasons = {entry["reason"] for entry in trace.to_dict() if entry["action"] == "dropped"}
    assert "address_like" in reasons
