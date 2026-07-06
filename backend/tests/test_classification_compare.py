"""Tests for finance DT policy scorer and classification compare."""

from __future__ import annotations

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult, LlmParty
from app.services.classification.classification_compare_service import compare_classification
from app.services.classification.finance_dt_policy_scorer import score_all_enabled_dts
from app.services.invoice.invoice_data import InvoiceData
from app.services.tenant.tenant_org_context import OrgContext
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID


def _dt03() -> DocumentTypeDefinition:
    return DocumentTypeDefinition.model_validate(
        {
            "code": "DT-03",
            "title": "Tax Invoice",
            "shortTitle": "Tax Inv",
            "klass": "Transactional",
            "posting": "Yes",
            "recognition_mode": "signals", "recognition_signals": ["heading_invoice"], "llm_prompt": "Tax invoice",
            "routeTarget": "Purchase Management",
            "enabled": True,
            "requiredFields": ["vendor", "invoice_no", "total"],
            "extractionFields": ["vendor", "invoice_no", "total"],
        }
    )


def _dt16() -> DocumentTypeDefinition:
    return DocumentTypeDefinition.model_validate(
        {
            "code": "DT-16",
            "title": "Bank Statement",
            "shortTitle": "Bank Stmt",
            "klass": "Non-transactional",
            "posting": "No",
            "recognition_mode": "prompt", "recognition_signals": [], "llm_prompt": "Bank statement",
            "routeTarget": "Vault",
            "enabled": True,
            "requiredFields": ["document_text"],
            "extractionFields": ["document_text"],
        }
    )


@pytest.fixture
def document_types():
    return [_dt03(), _dt16()]


def test_policy_scorer_picks_dt_with_more_fields(document_types) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.VALIDATING,
        vendor="Acme Supplies",
        invoice_no="INV-100",
        total=1200,
        abn="53004085616",
    )
    parsed = InvoiceData(
        vendor="Acme Supplies",
        invoice_no="INV-100",
        total=1200,
        abn="53004085616",
        document_text="TAX INVOICE",
    )
    result = score_all_enabled_dts(
        invoice=inv,
        parsed=parsed,
        document_types=document_types,
    )
    assert result.winner_dt == "DT-03"
    assert result.winner_confidence > 0


def test_compare_mismatch_goes_to_review(document_types) -> None:
    inv = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.VALIDATING, vendor="X")
    parsed = InvoiceData(vendor="X", document_text="quote only")
    policy = score_all_enabled_dts(invoice=inv, parsed=parsed, document_types=document_types)
    llm = LlmDocumentResult(
        suggested_dt="DT-03",
        confidence=0.9,
        reasoning="looks like tax invoice",
        seller=LlmParty(name="Vendor"),
        buyer=LlmParty(name="Acme Pty Ltd"),
        perspective="purchase",
    )
    org = OrgContext(legal_name="Acme Pty Ltd", abn="12345678901", default_perspective="buyer")
    decision = compare_classification(
        llm=llm,
        policy=policy,
        invoice=inv,
        parsed=parsed,
        document_types=document_types,
        org=org,
        ocr_sparse=False,
    )
    if llm.suggested_dt != policy.winner_dt:
        assert decision.auto_eligible is False
        assert any(r.value == "DT_MISMATCH" for r in decision.review_reasons)


def test_compare_llm_invalid(document_types) -> None:
    inv = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.VALIDATING)
    parsed = InvoiceData()
    policy = score_all_enabled_dts(invoice=inv, parsed=parsed, document_types=document_types)
    decision = compare_classification(
        llm=None,
        policy=policy,
        invoice=inv,
        parsed=parsed,
        document_types=document_types,
        org=OrgContext(),
    )
    assert decision.auto_eligible is False
