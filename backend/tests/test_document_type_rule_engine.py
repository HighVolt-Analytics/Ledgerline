
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Tests for config-driven document type classification."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.schemas.rule_book_config import RuleCondition, RuleConditionGroup, validate_rule_book_config_payload
from app.services.classification.document_type_classifier import classify_document_type
from app.services.classification.document_type_rule_engine import (
    is_user_defined_document_type,
    match_configured_document_type,
)
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem


def _invoice(**kwargs) -> Invoice:
    base = dict(id=1, tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.PARSING, currency="AUD")
    base.update(kwargs)
    return Invoice(**base)


def _parsed(**kwargs) -> InvoiceData:
    base = dict(
        vendor="Acme Supplies Pty Ltd",
        invoice_no="INV-1001",
        invoice_date=date(2026, 3, 1),
        total=Decimal("110.00"),
        line_items=[ParsedLineItem(description="Office paper", qty=Decimal("10"), amount=Decimal("100"))],
    )
    base.update(kwargs)
    return InvoiceData(**base)


def _dt_with_classifier(
    code: str,
    *,
    priority: int = 100,
    confidence: float = 0.9,
    children: list[RuleCondition],
) -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code=code,
        title=f"Test {code}",
        shortTitle=code,
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals", recognition_signals=["heading_invoice"], llm_prompt="",
        routeTarget="Expenses Management",
        enabled=True,
        classifier=DocumentTypeClassifier(
            enabled=True,
            priority=priority,
            confidence=confidence,
            root=RuleConditionGroup(operator="AND", children=children).model_dump(),
        ),
    )


def test_config_classifier_vendor_contains() -> None:
    invoice = _invoice(
        email_attachment_name="cloud-invoice.pdf",
        vendor="Directus Cloud",
    )
    parsed = _parsed(po_reference=None, vendor="Directus Cloud")
    doc_types = [
        _dt_with_classifier(
            "DT-99",
            priority=50,
            confidence=0.95,
            children=[RuleCondition(field="vendor", operator="contains", value="directus")],
        ),
    ]
    hit = match_configured_document_type(doc_types, invoice=invoice, parsed=parsed)
    assert hit is not None
    definition, source = hit
    assert definition.code == "DT-99"
    assert source == "config_classifier"


def test_classify_document_type_without_classifier_returns_unclassified() -> None:
    invoice = _invoice(vendor="Acme Supplies", invoice_no="INV-100", total=Decimal("1200"))
    parsed = _parsed(vendor="Acme Supplies", invoice_no="INV-100", total=Decimal("1200"))
    doc_types = [
        DocumentTypeDefinition(
            code="DT-03",
            title="Tax Invoice",
            shortTitle="Tax",
            klass="Transactional",
            posting="Yes",
            recognition_mode="signals", recognition_signals=["heading_invoice"], llm_prompt="",
            routeTarget="Purchase Management",
            enabled=True,
            required_fields=["vendor", "invoice_no", "total"],
        ),
    ]
    result = classify_document_type(invoice=invoice, parsed=parsed, document_types=doc_types)
    assert result.code == ""
    assert "No classifier matched" in result.reason


def test_is_user_defined_document_type_shipped_dt_code() -> None:
    defn = DocumentTypeDefinition(
        code="DT-01",
        title="PO goods invoice",
        shortTitle="PO goods",
        klass="Transactional",
        posting="Yes",
        routeTarget="Purchase Management",
    )
    assert is_user_defined_document_type(defn) is False


def test_is_user_defined_document_type_template_backed_org_code() -> None:
    defn = DocumentTypeDefinition(
        code="ORG-PO-1",
        title="PO copy",
        shortTitle="PO",
        klass="Non-transactional",
        posting="No",
        matrixTemplateCode="DT-02",
        routeTarget="Purchase Management",
    )
    assert is_user_defined_document_type(defn) is False


def test_is_user_defined_document_type_custom_org_code() -> None:
    defn = DocumentTypeDefinition(
        code="ORG-CUSTOM-1",
        title="Custom type",
        shortTitle="Custom",
        klass="Transactional",
        posting="Yes",
        routeTarget="Vault",
    )
    assert is_user_defined_document_type(defn) is True


def test_apply_user_defined_classifier_gate_does_not_crash_on_shipped_dt() -> None:
    from app.schemas.ocr_artifact import OcrArtifact
    from app.services.invoice.invoice_pipeline_phases import (
        GatePhaseResult,
        apply_user_defined_classifier_gate,
    )

    defn = DocumentTypeDefinition(
        code="DT-01",
        title="PO goods invoice",
        shortTitle="PO goods",
        klass="Transactional",
        posting="Yes",
        routeTarget="Purchase Management",
    )
    gate = GatePhaseResult(
        passed=True,
        confirmed_dt="DT-01",
        confirmed_confidence=0.92,
        review_reasons=[],
        llm_suggested_dt="DT-01",
        llm_confidence=0.92,
        llm_reasoning="Matches PO invoice",
        min_route_confidence=0.65,
        org_auto_route_min_confidence=0.65,
        dt_min_route_confidence=0.65,
    )
    ocr = OcrArtifact(text="TAX INVOICE\nPO 12345\nTotal $100")
    result = apply_user_defined_classifier_gate(
        gate,
        invoice=_invoice(),
        ocr=ocr,
        document_types=[defn],
    )
    assert result.passed is True
    assert result.confirmed_dt == "DT-01"
