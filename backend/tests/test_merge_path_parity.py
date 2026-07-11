"""Parity tests: legacy merge vs shape-aware fuse_line_items on fixtures A–F."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.extraction_orchestrator import (
    _collect_line_item_fusion_sources,
    _merge_line_items_from_sources,
)
from app.services.extraction.field_fusion_engine import fuse_line_items
from app.services.extraction.pdf_parser import parse_local_text
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _definition(**kwargs) -> DocumentTypeDefinition:
    base = dict(
        code="DT-01",
        title="Tax Invoice",
        shortTitle="Invoice",
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals",
        recognition_signals=["heading_invoice"],
        llm_prompt="",
        routeTarget="Purchase Management",
        classifier=DocumentTypeClassifier(),
        extraction_fields=["vendor", "invoice_no", "total", "line_items"],
    )
    base.update(kwargs)
    return DocumentTypeDefinition(**base)


def _ocr(text: str, payload: dict | None = None) -> OcrArtifact:
    return OcrArtifact(success=True, text=text, text_length=len(text), payload_json=payload or {})


def _assert_parity(
    parsed: InvoiceData,
    text: str,
    payload: dict,
    *,
    dt_definition: DocumentTypeDefinition | None = None,
) -> None:
    legacy = _merge_line_items_from_sources(parsed, text, payload)
    sources = _collect_line_item_fusion_sources(parsed, text, payload)
    fused = fuse_line_items(
        sources,
        dt_definition=dt_definition,
        merged=parsed,
        ocr_text=text,
        payload_dict=payload,
    )
    assert len(fused) == len(legacy)
    for left, right in zip(legacy, fused, strict=False):
        assert (left.description or "").lower() == (right.description or "").lower()
        assert left.qty == right.qty
        assert left.unit_price == right.unit_price
        assert left.amount == right.amount


def test_merge_path_parity_fixture_a_product_table() -> None:
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
                source="llm",
            ),
        ]
    )
    _assert_parity(parsed, text, {"table_line_items": table_rows})


def test_merge_path_parity_fixture_b_qty_only() -> None:
    text = (_FIXTURES_DIR / "qty_only_table_ocr.txt").read_text(encoding="utf-8")
    payload = {
        "table_line_items": [
            {
                "description": "CPU CHIPS 14 Gen I3 14100  I3-14100  8471.50.00",
                "qty": "150",
            },
            {
                "description": "CPU CHIPS 14 Gen I5 14400  I5-14400  8471.50.00",
                "qty": "70",
            },
        ]
    }
    parsed = InvoiceData(
        line_items=[
            ParsedLineItem(description="CPU CHIPS 14 Gen I3 14100", qty=Decimal("150"), source="llm"),
        ]
    )
    _assert_parity(parsed, text, payload)


def test_merge_path_parity_fixture_c_charge_lines() -> None:
    from tests.test_commercial_invoice_extraction import _COMMERCIAL_OCR

    parsed = InvoiceData(
        line_items=[
            ParsedLineItem(description="Freight", qty=Decimal("1"), amount=Decimal("500"), source="llm"),
        ]
    )
    _assert_parity(parsed, _COMMERCIAL_OCR, {})


def test_merge_path_parity_fixture_d_no_table() -> None:
    text = "TAX INVOICE\nVendor: Acme\nTotal: 100.00"
    parsed = InvoiceData(
        line_items=[ParsedLineItem(description="LLM Wrong", amount=Decimal("999"), source="llm")],
        line_items_grounding="unverifiable",
    )
    _assert_parity(parsed, text, {})


def test_merge_path_parity_fixture_e_noise_anchor() -> None:
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
                description="CPU CHIPS 14 Gen 13 14100 | CHINA | 9.70 | 10.60 | 1 | 81 X 61 X 97",
                qty=Decimal("150"),
                source="llm",
            ),
        ],
    )
    _assert_parity(parsed, text, payload)


def test_merge_path_parity_fixture_f_partial_trust() -> None:
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
            ParsedLineItem(description="Widget A", qty=Decimal("2"), unit_price=Decimal("10"), amount=Decimal("20"), source="llm"),
            ParsedLineItem(description="Widget B", qty=Decimal("1"), unit_price=None, amount=Decimal("5"), source="llm"),
            ParsedLineItem(description="Widget C", qty=Decimal("3"), unit_price=Decimal("2"), amount=Decimal("6"), source="llm"),
            ParsedLineItem(description="Widget D", qty=Decimal("1"), unit_price=Decimal("8"), amount=Decimal("8"), source="llm"),
        ],
        raw_fields={"_line_items_confidence": 0.5},
    )
    _assert_parity(parsed, text, {"table_line_items": table_rows})
