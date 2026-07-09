"""DI authority over conflicting LLM extracted_fields."""

from __future__ import annotations

from app.schemas.llm_document import LlmDocumentResult, LlmParty
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.extraction_field_values import merge_extracted_fields_with_authority
from app.services.extraction.llm_document_service import llm_result_to_invoice_data
from app.services.tenant.tenant_org_context import OrgContext


def test_merge_extracted_fields_di_wins_over_llm_proforma() -> None:
    ocr_text = "INVOICE NO. : 260371344/\nPROFORMA INVOICE NO: 2603110950SA DATED: 11.05.2026"
    payload = {
        "invoice_fields": {
            "invoice_no": "260371344",
            "vendor": "WALTON DIGI-TECH INDUSTRIES LIMITED",
        }
    }
    merged = merge_extracted_fields_with_authority(
        base={},
        llm_extracted={"invoice_no": "2603110950SA DATED: 11.05.2026"},
        payload=payload,
        selected_keys=["invoice_no", "vendor"],
        ocr_text=ocr_text,
    )
    assert merged["invoice_no"] == "260371344"


def test_llm_result_to_invoice_data_respects_di_extracted_fields() -> None:
    ocr_text = "INVOICE NO. : 260371344/\nPROFORMA INVOICE NO: 2603110950SA DATED: 11.05.2026"
    ocr = OcrArtifact(
        text=ocr_text,
        text_length=len(ocr_text),
        payload_json={
            "invoice_fields": {
                "invoice_no": "260371344",
            }
        },
    )
    llm = LlmDocumentResult(
        invoice_no="2603110950SA DATED: 11.05.2026",
        extracted_fields={"invoice_no": "2603110950SA DATED: 11.05.2026"},
        seller=LlmParty(),
        buyer=LlmParty(),
    )
    parsed = llm_result_to_invoice_data(
        llm,
        ocr=ocr,
        selected_keys=["invoice_no"],
        org=OrgContext(),
    )
    assert parsed.invoice_no == "260371344"
    assert parsed.extracted_fields.get("invoice_no") == "260371344"
