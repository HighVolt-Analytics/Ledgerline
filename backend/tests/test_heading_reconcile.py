"""Heading-based classification reconcile for import supporting documents."""

from __future__ import annotations

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.schemas.rule_book_config import AiClassificationConfig
from app.services.classification.segment_heading_classification import (
    filter_configured_matches_for_heading,
    heading_conflicts_with_definition,
    list_heading_aware_document_type_matches,
)
from app.services.invoice.invoice_data import InvoiceData
from app.services.invoice.invoice_pipeline_phases import reconcile_llm_dt_with_heading
from app.tenant_ids import TESTING_TENANT_UUID


def _classifier(**kwargs) -> DocumentTypeClassifier:
    base = {
        "enabled": True,
        "priority": 50,
        "confidence": 0.88,
        "root": {"type": "group", "operator": "AND", "children": []},
    }
    base.update(kwargs)
    return DocumentTypeClassifier.model_validate(base)


def _dt(**kwargs) -> DocumentTypeDefinition:
    base = {
        "code": "DT-01",
        "title": "PO-based goods invoice",
        "shortTitle": "Goods invoice",
        "klass": "Transactional",
        "posting": "Yes",
        "recognition_mode": "signals",
        "recognition_signals": [],
        "llm_prompt": "",
        "routeTarget": "Purchase Management",
        "enabled": True,
        "playbookProfile": "po_goods",
        "classifier": _classifier(priority=180),
        "requiredFields": ["vendor", "invoice_no", "total", "line_items"],
        "extractionFields": ["vendor", "invoice_no", "total", "line_items"],
    }
    base.update(kwargs)
    return DocumentTypeDefinition.model_validate(base)


def _coo_dt() -> DocumentTypeDefinition:
    return _dt(
        code="DT-26",
        title="Certificate of Origin",
        shortTitle="Certificate of Origin",
        klass="Non-actionable",
        posting="NEVER",
        playbookProfile="supporting",
        validationProfile="non_actionable",
        requiredFields=[],
        extractionFields=["vendor", "invoice_no"],
        classifier=_classifier(priority=65),
    )


def _ccp_dt() -> DocumentTypeDefinition:
    return _dt(
        code="DT-CCP",
        title="Cargo Clearance Permit",
        shortTitle="Cargo Clearance Permit",
        klass="Non-actionable",
        posting="NEVER",
        playbookProfile="supporting",
        validationProfile="non_actionable",
        requiredFields=[],
        extractionFields=["permit_no", "vendor"],
        classifier=_classifier(priority=40),
    )


def _dt02() -> DocumentTypeDefinition:
    return _dt(
        code="DT-02",
        title="PO-based services invoice",
        shortTitle="Services invoice",
        playbookProfile="po_services",
        classifier=_classifier(priority=25),
    )


def test_heading_conflicts_rejects_dt01_for_coo() -> None:
    coo_heading = "certificate_of_origin"
    assert heading_conflicts_with_definition(coo_heading, _dt()) is True
    assert heading_conflicts_with_definition(coo_heading, _coo_dt()) is False


def test_heading_conflicts_rejects_dt02_for_customs_permit() -> None:
    assert heading_conflicts_with_definition("customs_permit", _dt02()) is True
    assert heading_conflicts_with_definition("customs_permit", _ccp_dt()) is False


def test_filter_configured_matches_excludes_transactional_for_coo_heading() -> None:
    invoice = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PENDING)
    parsed = InvoiceData(
        document_text="CERTIFICATE OF ORIGIN\nINVOICE NO. 260371344",
        invoice_no="260371344",
    )
    matches = [
        (_dt(), "classifier"),
        (_coo_dt(), "classifier"),
    ]
    filtered = filter_configured_matches_for_heading(
        matches,
        heading_kind="certificate_of_origin",
        invoice=invoice,
        parsed=parsed,
    )
    codes = {row[0].code for row in filtered}
    assert "DT-01" not in codes
    assert "DT-26" in codes


def test_reconcile_heading_adopts_coo_dt() -> None:
    ocr = OcrArtifact(
        success=True,
        text="REPUBLIC OF SINGAPORE CERTIFICATE OF ORIGIN/PROCESSING\nINVOICE NO. 260371344",
        text_length=80,
    )
    llm = LlmDocumentResult(
        suggested_dt="DT-02",
        confidence=0.95,
        reasoning="looked like invoice",
        perspective="purchase",
        document_heading="CERTIFICATE OF ORIGIN",
    )
    invoice = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PENDING)
    updated, detail = reconcile_llm_dt_with_heading(
        llm,
        invoice=invoice,
        ocr=ocr,
        document_types=[_dt02(), _coo_dt()],
        ai_cfg=AiClassificationConfig(auto_route_min_confidence=0.65),
    )
    assert detail is not None
    assert detail["adopted_dt"] == "DT-26"
    assert detail["heading_kind"] == "certificate_of_origin"
    assert updated is not None
    assert updated.suggested_dt == "DT-26"


def test_reconcile_heading_fills_empty_dt_for_ccp() -> None:
    ocr = OcrArtifact(
        success=True,
        text="CARGO CLEARANCE PERMIT\nPERMIT NO: OD6F479670G",
        text_length=50,
    )
    llm = LlmDocumentResult(
        suggested_dt="",
        confidence=0.95,
        reasoning="",
        perspective="purchase",
    )
    invoice = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PENDING)
    updated, detail = reconcile_llm_dt_with_heading(
        llm,
        invoice=invoice,
        ocr=ocr,
        document_types=[_dt(), _ccp_dt()],
        ai_cfg=AiClassificationConfig(auto_route_min_confidence=0.65),
    )
    assert detail is not None
    assert detail["adopted_dt"] == "DT-CCP"
    assert detail["reason"] == "empty_llm_suggested_dt"
    assert updated is not None
    assert updated.suggested_dt == "DT-CCP"


def test_list_heading_aware_matches_skips_po_goods_for_coo() -> None:
    invoice = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PENDING)
    parsed = InvoiceData(
        document_text="CERTIFICATE OF ORIGIN\nInvoice 260371344",
        invoice_no="260371344",
    )
    matches = list_heading_aware_document_type_matches(
        [_dt(), _coo_dt()],
        invoice=invoice,
        parsed=parsed,
    )
    codes = {row[0].code for row in matches}
    assert "DT-01" not in codes
