
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
from app.services.document_type_classifier import classify_document_type
from app.services.document_type_rule_engine import match_configured_document_type
from app.services.invoice_data import InvoiceData, ParsedLineItem


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
        fraudRisk="low",
        oneLine="test",
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


def test_config_classifier_wins_over_heuristic(capture_config) -> None:
    invoice = _invoice(email_attachment_name="tax-invoice-mkt.pdf")
    parsed = _parsed(po_reference=None)
    doc_types = list(capture_config.document_types)
    doc_types.append(
        _dt_with_classifier(
            "DT-88",
            priority=1,
            confidence=0.91,
            children=[
                RuleCondition(field="attachment_name", operator="contains", value="tax-invoice")
            ],
        )
    )
    result = classify_document_type(invoice=invoice, parsed=parsed, document_types=doc_types)
    assert result.code == "DT-88"
    assert result.confidence >= 0.85
    assert "Rule book classifier" in result.reason


def test_seeded_dt03_classifier_matches_grn_upload(capture_config) -> None:
    invoice = _invoice(email_attachment_name="GRN-PO-44871.pdf")
    parsed = _parsed(po_reference="PO-44871", invoice_no=None)
    result = classify_document_type(
        invoice=invoice,
        parsed=parsed,
        document_types=capture_config.document_types,
        parse_confidence="high",
    )
    assert result.code == "DT-03"
    assert result.confidence >= 0.85
