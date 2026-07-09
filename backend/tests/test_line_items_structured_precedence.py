"""Structured table precedence over text qty parser."""

from __future__ import annotations

from decimal import Decimal

from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.extraction_orchestrator import merge_extraction_sources
from app.services.invoice.invoice_data import ParsedLineItem
from app.services.extraction.line_item_noise_patterns import is_noise_line_item_row
from app.services.extraction.pdf_parser import parse_local_text


def _ocr(text: str, payload: dict | None = None) -> OcrArtifact:
    return OcrArtifact(text=text, sparse=False, text_length=len(text), payload_json=payload or {})


def test_structured_table_blocks_text_qty_union() -> None:
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
    parsed = parse_local_text(text)
    merged = merge_extraction_sources(parsed, _ocr(text, payload))
    assert len(merged.line_items or []) == 1
    assert "CPU CHIPS" in (merged.line_items[0].description or "")


def test_noise_pattern_flags_address_and_reference_rows() -> None:
    assert is_noise_line_item_row("217 Henderson Road, Singapore 159555", Decimal("159555"))
    assert is_noise_line_item_row("DOCUMENTARY CREDIT NUMBER: 308526022170 DATED", Decimal("260316"))


def test_noise_pattern_allows_product_row() -> None:
    item = ParsedLineItem(description="CPU CHIPS 14 Gen 13 14100", qty=Decimal("150"))
    assert not is_noise_line_item_row(item.description, item.qty)
