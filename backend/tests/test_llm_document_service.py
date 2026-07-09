"""Tests for LLM document result schema validation."""

from __future__ import annotations

import pytest
from decimal import Decimal
from pydantic import ValidationError

from app.schemas.llm_document import LlmDocumentResult, LlmParty
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.llm_document_service import llm_result_to_invoice_data


def _extract_json_keys_line(system: str) -> str:
    marker = "Return JSON only with keys:\n"
    start = system.index(marker) + len(marker)
    end = system.index(".", start)
    return system[start:end]


def test_llm_result_accepts_valid_payload() -> None:
    result = LlmDocumentResult.model_validate(
        {
            "suggested_dt": "dt-03",
            "confidence": 0.88,
            "reasoning": "Tax invoice with vendor and total",
            "perspective": "purchase",
        }
    )
    assert result.suggested_dt == "DT-03"
    assert result.confidence == pytest.approx(0.88)
    assert result.perspective == "purchase"


def test_llm_result_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        LlmDocumentResult.model_validate({"suggested_dt": "DT-03", "confidence": 1.5})


def test_llm_result_normalizes_unknown_perspective() -> None:
    result = LlmDocumentResult.model_validate(
        {"suggested_dt": "DT-16", "confidence": 0.5, "perspective": "maybe"}
    )
    assert result.perspective == "unknown"


def test_llm_result_coerces_empty_decimal_strings() -> None:
    result = LlmDocumentResult.model_validate(
        {
            "suggested_dt": "DT-03",
            "confidence": 0.8,
            "subtotal": "",
            "line_items": [{"description": "Widget", "unit_price": "", "amount": "10"}],
        }
    )
    assert result.subtotal is None
    assert result.line_items[0].unit_price is None
    assert result.line_items[0].amount == Decimal("10")


def test_llm_party_syncs_abn_to_tax_id() -> None:
    party = LlmParty.model_validate({"name": "Acme Pty Ltd", "abn": "51824753556"})
    assert party.tax_id == "51824753556"
    assert party.abn == "51824753556"

    party2 = LlmParty.model_validate(
        {"name": "Spectra", "tax_id": "199904042N", "address": "Singapore"}
    )
    assert party2.abn == "199904042N"
    assert party2.address == "Singapore"


    result = LlmDocumentResult.model_validate(
        {
            "suggested_dt": "DT-03",
            "confidence": 0.8,
            "vendor": {"name": "SPECTRA INNOVATIONS", "abn": "199904042N"},
        }
    )
    assert result.vendor == "SPECTRA INNOVATIONS"


def test_llm_result_accepts_null_optional_strings() -> None:
    """Clearance permits and similar types often omit invoice_no / due_date as null."""
    result = LlmDocumentResult.model_validate(
        {
            "suggested_dt": "DT-02",
            "confidence": 0.9,
            "invoice_no": None,
            "invoice_date": None,
            "due_date": None,
            "po_reference": None,
            "vendor": "SPECTRA INNOVATIONS PTE LTD",
            "seller": {"name": "SPECTRA INNOVATIONS PTE LTD"},
        }
    )
    assert result.invoice_no == ""
    assert result.invoice_date == ""
    assert result.due_date == ""
    assert result.po_reference == ""
    assert result.vendor == "SPECTRA INNOVATIONS PTE LTD"


def test_llm_result_to_invoice_data_prefers_seller_for_vendor() -> None:
    llm = LlmDocumentResult(
        suggested_dt="DT-02",
        confidence=0.9,
        seller=LlmParty(name="SPECTRA INNOVATIONS PTE LTD"),
        perspective="purchase",
    )
    parsed = llm_result_to_invoice_data(
        llm,
        ocr=OcrArtifact(
            success=True,
            text="SPECTRA INNOVATIONS PTE LTD\nPermit",
            text_length=30,
        ),
    )
    assert parsed.vendor == "SPECTRA INNOVATIONS PTE LTD"


def test_llm_result_schema_omits_currency_default_when_not_in_payload() -> None:
    result = LlmDocumentResult.model_validate(
        {"suggested_dt": "DT-02", "confidence": 0.9, "vendor": "Permit Authority"}
    )
    assert result.currency == ""


def test_llm_result_maps_so_reference_cost_centre_and_bank_name() -> None:
    llm = LlmDocumentResult(
        suggested_dt="DT-03",
        confidence=0.9,
        so_reference="SO-9001",
        cost_centre="CC-42",
        bank_bsb="062-000",
        bank_account="12345678",
        bank_name="Commonwealth Bank",
        currency="SGD",
        total=Decimal("100"),
    )
    parsed = llm_result_to_invoice_data(
        llm,
        ocr=OcrArtifact(success=True, text="SO-9001 CC-42", text_length=14),
    )
    assert parsed.cost_centre == "CC-42"
    assert parsed.currency == "SGD"
    assert parsed.extracted_fields["so_reference"] == "SO-9001"
    assert parsed.extracted_fields["bank_name"] == "Commonwealth Bank"
    assert "Commonwealth Bank" in parsed.extracted_fields["bank_details"]
    assert parsed.bank_bsb == "062-000"
    assert parsed.bank_account == "12345678"


def test_build_structure_extract_prompts_lists_configured_scalar_keys() -> None:
    from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
    from app.services.extraction.llm_document_service import build_structure_extract_prompts
    from app.services.tenant.tenant_org_context import OrgContext

    dt = DocumentTypeDefinition(
        code="DT-01",
        title="Invoice",
        shortTitle="Invoice",
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals",
        recognition_signals=["heading_invoice"],
        llm_prompt="",
        routeTarget="Purchase Management",
        classifier=DocumentTypeClassifier(),
        extraction_fields=[
            "vendor",
            "invoice_no",
            "so_reference",
            "cost_centre",
            "bank_details",
        ],
    )
    system, _user = build_structure_extract_prompts(
        ocr=OcrArtifact(success=True, text="Invoice", text_length=7),
        org=OrgContext(),
        document_types=[dt],
        confirmed_dt="DT-01",
    )
    assert "so_reference" in system
    assert "cost_centre" in system
    assert "bank_name" in system
    json_keys = _extract_json_keys_line(system)
    assert "po_reference" not in json_keys
    assert "line_items" not in json_keys


def test_build_structure_extract_prompts_requires_verbatim_ocr_values() -> None:
    from app.services.extraction.llm_document_service import build_extract_system_prompt
    from app.services.tenant.tenant_org_context import OrgContext

    system = build_extract_system_prompt(OrgContext(), selected_keys=["vendor", "total"])
    assert "verbatim" in system.lower()
    assert "do not self-sum" in system.lower()
    assert "CORE RULES" in system
    assert "EDGE CASE RULES" in system
    assert "OUTPUT DISCIPLINE" in system
    assert "suggested_dt must match confirmed_dt" in system
    assert "seller and buyer are objects" in system
    assert "PROFORMA" in system
    assert "counterparty_source" in system


def test_build_structure_extract_prompts_omits_unconfigured_line_items() -> None:
    from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
    from app.services.extraction.llm_document_service import build_structure_extract_prompts
    from app.services.tenant.tenant_org_context import OrgContext

    dt = DocumentTypeDefinition(
        code="DT-08",
        title="Expense",
        shortTitle="Expense",
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals",
        recognition_signals=["heading_invoice"],
        llm_prompt="",
        routeTarget="Expenses Management",
        classifier=DocumentTypeClassifier(),
        extraction_fields=["vendor", "total", "due_date"],
    )
    system, _user = build_structure_extract_prompts(
        ocr=OcrArtifact(success=True, text="Receipt", text_length=7),
        org=OrgContext(),
        document_types=[dt],
        confirmed_dt="DT-08",
    )
    assert "vendor" in system
    json_keys = _extract_json_keys_line(system)
    assert "line_items" not in json_keys


def test_build_extract_system_prompt_qty_only_table_does_not_break_format() -> None:
    from pathlib import Path

    from app.services.extraction.llm_document_service import build_extract_system_prompt
    from app.services.tenant.tenant_org_context import OrgContext

    text = Path("tests/fixtures/qty_only_table_ocr.txt").read_text(encoding="utf-8")
    ocr = OcrArtifact(success=True, text=text, text_length=len(text), payload_json={})
    system = build_extract_system_prompt(
        OrgContext(),
        selected_keys=["line_items", "invoice_no"],
        ocr=ocr,
    )
    assert "QTY-ONLY TABLE" in system
    assert "{description, qty}" in system


def test_llm_result_sanitizes_metadata_line_items() -> None:
    llm = LlmDocumentResult.model_validate(
        {
            "suggested_dt": "DT-03",
            "confidence": 0.9,
            "vendor": "Acme Pty Ltd",
            "seller": {"name": "Acme Pty Ltd"},
            "line_items": [
                {"description": "Customer:", "qty": "1"},
                {
                    "description": "Widget assembly",
                    "qty": "2",
                    "unit_price": "50",
                    "amount": "100",
                },
            ],
        }
    )
    parsed = llm_result_to_invoice_data(
        llm,
        ocr=OcrArtifact(
            success=True,
            text="TAX INVOICE\nAcme Pty Ltd\nWidget assembly    2    50.00    100.00",
            text_length=60,
        ),
    )
    assert len(parsed.line_items) == 1
    assert parsed.line_items[0].description == "Widget assembly"
    assert parsed.line_items[0].amount == Decimal("100")
