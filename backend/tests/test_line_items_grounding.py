"""DI-first line item extraction: resolver, grounding, and merge."""

from __future__ import annotations

import json
from decimal import Decimal

from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.extraction_orchestrator import merge_extraction_sources
from app.services.extraction.field_grounding_service import ground_parsed_fields
from app.services.extraction.line_items_parser import (
    build_line_items_presentation_prompt,
    document_has_product_table,
    normalize_di_line_items_for_prompt,
    resolve_line_items_from_ocr_payload,
)
from app.services.extraction.llm_document_service import (
    build_extract_system_prompt,
    build_llm_user_payload,
    llm_result_to_invoice_data,
)
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem
from app.services.tenant.tenant_org_context import OrgContext


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


def test_resolve_line_items_prefers_di_over_table() -> None:
    payload = {
        "di_line_items": [{"description": "DI Widget", "qty": "2", "amount": "20"}],
        "table_line_items": [{"description": "Table Widget", "qty": "1", "amount": "10"}],
    }
    rows = resolve_line_items_from_ocr_payload(payload)
    assert rows is not None
    assert len(rows) == 2
    assert rows[0].description == "DI Widget"
    assert any(row.description == "Table Widget" for row in rows)


def test_document_has_product_table_from_di_payload() -> None:
    payload = {"di_line_items": [{"description": "Widget", "amount": "5"}]}
    assert document_has_product_table("", payload)


def test_document_has_product_table_from_ocr_grid() -> None:
    text = """
DESCRIPTION QTY UNIT PRICE AMOUNT
Widget A 2 10.00 20.00
Widget B 1 15.00 15.00
"""
    assert document_has_product_table(text, {})


def test_document_has_product_table_false_for_plain_invoice() -> None:
    text = "TAX INVOICE\nVendor: Acme\nTotal: 100.00"
    assert not document_has_product_table(text, {})


def test_normalize_di_line_items_for_prompt() -> None:
    items = [
        ParsedLineItem(description="Widget", qty=Decimal("2"), unit_price=Decimal("10"), amount=Decimal("20")),
    ]
    rows = normalize_di_line_items_for_prompt(items)
    assert rows == [
        {
            "row_index": 1,
            "description": "Widget",
            "qty": "2",
            "unit_price": "10",
            "amount": "20",
        }
    ]


def test_build_line_items_presentation_prompt_di_mode() -> None:
    lines = build_line_items_presentation_prompt(di_rows_present=True, ocr_table_present=False)
    joined = "\n".join(lines)
    assert "azure_di_line_items" in joined
    assert "row-for-row" in joined


def test_ground_parsed_fields_clears_llm_line_items_when_di_present() -> None:
    parsed = InvoiceData(
        line_items=[ParsedLineItem(description="LLM invented", amount=Decimal("99"))],
    )
    payload = {"di_line_items": [{"description": "DI row", "amount": "10"}]}
    grounded = ground_parsed_fields(parsed, "Invoice text", ["line_items"], payload)
    assert grounded.line_items == []


def test_ground_parsed_fields_clears_line_items_when_no_table() -> None:
    parsed = InvoiceData(
        line_items=[ParsedLineItem(description="LLM invented", amount=Decimal("99"))],
    )
    grounded = ground_parsed_fields(
        parsed,
        "TAX INVOICE\nVendor: Acme\nTotal: 100.00",
        ["line_items"],
        {},
    )
    assert grounded.line_items == []


def test_merge_extraction_sources_uses_di_rows_not_llm() -> None:
    ocr = OcrArtifact(
        success=True,
        text="TAX INVOICE\nVendor: Acme\nDESCRIPTION QTY AMOUNT\nWidget 2 20.00",
        text_length=60,
        payload_json={
            "di_line_items": [
                {"description": "DI Widget", "qty": "2", "unit_price": "10", "amount": "20"},
            ]
        },
    )
    parsed = InvoiceData(
        vendor="Acme",
        document_text=ocr.text,
        line_items=[ParsedLineItem(description="LLM Wrong", amount=Decimal("999"))],
    )
    merged = merge_extraction_sources(parsed, ocr, dt_definition=_definition())
    assert len(merged.line_items) == 1
    assert merged.line_items[0].description == "DI Widget"
    assert merged.line_items[0].amount == Decimal("20")


def test_merge_extraction_sources_empty_when_no_table() -> None:
    ocr = OcrArtifact(
        success=True,
        text="TAX INVOICE\nVendor: Acme\nTotal: 100.00",
        text_length=35,
    )
    parsed = InvoiceData(
        vendor="Acme",
        document_text=ocr.text,
        line_items=[ParsedLineItem(description="LLM Wrong", amount=Decimal("999"))],
    )
    merged = merge_extraction_sources(parsed, ocr, dt_definition=_definition())
    assert merged.line_items == []


def test_llm_result_skips_line_items_when_di_present() -> None:
    llm = LlmDocumentResult.model_validate(
        {
            "suggested_dt": "DT-01",
            "confidence": 0.9,
            "vendor": "Acme",
            "seller": {"name": "Acme"},
            "line_items": [
                {"description": "LLM Wrong", "qty": "1", "amount": "999"},
            ],
        }
    )
    parsed = llm_result_to_invoice_data(
        llm,
        ocr=OcrArtifact(
            success=True,
            text="Invoice",
            text_length=7,
            payload_json={
                "di_line_items": [{"description": "DI row", "qty": "1", "amount": "10"}],
            },
        ),
    )
    assert parsed.line_items == []


def test_build_llm_user_payload_includes_azure_di_line_items() -> None:
    ocr = OcrArtifact(
        success=True,
        text="Invoice",
        text_length=7,
        payload_json={
            "di_line_items": [{"description": "Widget", "qty": "1", "amount": "10"}],
        },
    )
    raw = build_llm_user_payload(
        ocr=ocr,
        org=OrgContext(),
        document_types=[_definition()],
        selected_keys=["line_items", "vendor"],
    )
    payload = json.loads(raw)
    assert payload["ocr"]["line_items_source"] == "azure_di"
    assert payload["ocr"]["line_items_row_count"] == 1
    assert payload["ocr"]["azure_di_line_items"][0]["description"] == "Widget"
    assert "di_line_items" not in payload["ocr"]


def test_build_extract_system_prompt_di_line_items_rules() -> None:
    ocr = OcrArtifact(
        success=True,
        text="Invoice",
        text_length=7,
        payload_json={
            "di_line_items": [{"description": "Widget", "qty": "1", "amount": "10"}],
        },
    )
    system = build_extract_system_prompt(
        OrgContext(),
        selected_keys=["line_items", "vendor"],
        ocr=ocr,
    )
    assert "AZURE DI" in system
    assert "azure_di_line_items" in system
