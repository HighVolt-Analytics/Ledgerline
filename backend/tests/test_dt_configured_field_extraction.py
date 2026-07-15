"""DT-configured scalar fields must extract from printed evidence (newline KV, layout KV)."""

from __future__ import annotations

from decimal import Decimal

from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.custom_field_ocr_extractors import extract_label_value_fields_from_text
from app.services.extraction.extraction_orchestrator import merge_extraction_sources
from app.services.extraction.layout_field_extractor import extract_key_value_fields
from app.services.invoice.invoice_data import InvoiceData


def _dt(*, extraction_fields: list[str]) -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code="DT-09",
        title="Tax invoice",
        shortTitle="Tax invoice",
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals",
        recognition_signals=["heading_invoice"],
        llm_prompt="",
        routeTarget="Purchase Management",
        playbook_profile="services_invoice",
        classifier=DocumentTypeClassifier(),
        extraction_fields=extraction_fields,
        required_fields=["vendor", "invoice_no", "total"],
        absent_fields=[],
        enabled=True,
    )


NEWLINE_KV_TEXT = """
TAX INVOICE
Vendor: Deloitte Touche Tohmatsu
ABN
74 490 121 060
Invoice No
DTT-2026-A4427
Invoice Date
2026-05-11
Due Date
2026-06-10
Currency
AUD
Cost Centre
FIN-ADVISORY
Total
8360.00
"""


def test_extract_key_value_fields_newline_currency_cost_centre_abn() -> None:
    found = extract_key_value_fields(None, NEWLINE_KV_TEXT)
    assert found.get("currency") == "AUD"
    assert found.get("cost_centre") == "FIN-ADVISORY"
    assert "490" in (found.get("abn") or "")
    # Must not bind GST from "TAX INVOICE".
    assert found.get("gst") != "INVOICE"


def test_label_value_backfill_supports_newline_kv() -> None:
    found = extract_label_value_fields_from_text(
        NEWLINE_KV_TEXT,
        ["currency", "cost_centre", "abn"],
    )
    assert found.get("currency") == "AUD"
    assert found.get("cost_centre") == "FIN-ADVISORY"
    assert "490" in (found.get("abn") or "")


def test_merge_applies_dt_configured_currency_cost_centre_abn() -> None:
    defn = _dt(
        extraction_fields=[
            "vendor",
            "abn",
            "invoice_no",
            "invoice_date",
            "due_date",
            "currency",
            "cost_centre",
            "total",
            "line_items",
        ]
    )
    ocr = OcrArtifact(
        success=True,
        text=NEWLINE_KV_TEXT,
        text_length=len(NEWLINE_KV_TEXT),
        layout_kv={},
        payload_json={},
    )
    merged = merge_extraction_sources(InvoiceData(), ocr, dt_definition=defn)
    assert merged.currency == "AUD"
    assert merged.cost_centre == "FIN-ADVISORY"
    assert merged.abn and "74490121060" in merged.abn.replace(" ", "")
    assert merged.invoice_no == "DTT-2026-A4427"
    assert merged.total == Decimal("8360.00")


def test_sync_abn_from_seller_abn_evidence() -> None:
    defn = _dt(extraction_fields=["abn", "vendor", "invoice_no", "total"])
    parsed = InvoiceData(
        vendor="Deloitte Touche Tohmatsu",
        invoice_no="DTT-1",
        total=Decimal("100"),
        abn=None,
        extracted_fields={"seller_abn": "74 490 121 060"},
        document_text="Deloitte Touche Tohmatsu\nABN 74 490 121 060\nInvoice DTT-1\nTotal 100.00\n",
    )
    ocr = OcrArtifact(
        success=True,
        text=parsed.document_text or "",
        text_length=len(parsed.document_text or ""),
        payload_json={},
    )
    merged = merge_extraction_sources(parsed, ocr, dt_definition=defn)
    assert merged.abn and "74490121060" in merged.abn.replace(" ", "")
