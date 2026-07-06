"""Org context in LLM classify payload and system prompts."""

from __future__ import annotations

import json

from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.llm_document_service import (
    build_classify_system_prompt,
    build_extract_system_prompt,
    build_llm_user_payload,
)
from app.services.tenant.tenant_org_context import OrgContext, infer_perspective


def _org() -> OrgContext:
    return OrgContext(
        legal_name="Acme Manufacturing Pty Ltd",
        abn="12345678901",
        aliases=["Acme Mfg"],
        default_perspective="buyer",
        intake_summary="Supplier tax invoices and GRNs.",
        classification_hints="Prefer GRN when PO and delivery note present.",
    )


def test_build_llm_user_payload_includes_org_brief() -> None:
    from app.schemas.document_type import DocumentTypeDefinition

    ocr = OcrArtifact(
        success=True,
        sparse=False,
        text="TAX INVOICE Acme supplier",
        text_length=24,
        di_model="prebuilt-layout",
    )
    dt = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-01",
            "title": "Invoice",
            "shortTitle": "Invoice",
            "klass": "Transactional",
            "posting": "Yes",
            "recognition_mode": "signals",
            "recognition_signals": ["heading_invoice"],
            "routeTarget": "Purchase Management",
            "enabled": True,
        }
    )
    raw = build_llm_user_payload(ocr=ocr, org=_org(), document_types=[dt])
    payload = json.loads(raw)
    tenant = payload["tenant"]
    assert tenant["legal_name"] == "Acme Manufacturing Pty Ltd"
    assert tenant["intake_summary"] == "Supplier tax invoices and GRNs."
    assert tenant["classification_hints"].startswith("Prefer GRN")
    assert "extraction_hints" not in tenant
    catalogue = payload["catalogue"]
    assert len(catalogue) == 1
    assert catalogue[0]["code"] == "DT-01"
    assert catalogue[0]["recognition_mode"] == "signals"
    assert "one_line" not in catalogue[0]


def test_build_classify_system_prompt_includes_role_and_guidance() -> None:
    prompt = build_classify_system_prompt(_org())
    assert "accounts payable" in prompt.lower()
    assert "Typical intake:" in prompt
    assert "Tenant guidance:" in prompt
    assert "Supplier tax invoices" in prompt


def test_build_extract_system_prompt_omits_extraction_guidance() -> None:
    prompt = build_extract_system_prompt(_org())
    assert "Tenant extraction guidance:" not in prompt
    assert "accounts payable" in prompt.lower()


def test_infer_perspective_buyer_default_when_unknown() -> None:
    org = OrgContext(default_perspective="buyer")
    assert (
        infer_perspective(
            org=org,
            seller_name="Vendor Co",
            seller_abn="",
            buyer_name="Someone Else",
            buyer_abn="",
            llm_perspective="unknown",
        )
        == "purchase"
    )


def test_infer_perspective_mixed_stays_unknown_without_party_match() -> None:
    org = OrgContext(default_perspective="mixed")
    assert (
        infer_perspective(
            org=org,
            seller_name="Vendor Co",
            seller_abn="",
            buyer_name="Someone Else",
            buyer_abn="",
            llm_perspective="unknown",
        )
        == "unknown"
    )
