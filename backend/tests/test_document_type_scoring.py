"""Tests for evidence-based document type confidence scoring."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.rule_book_config import validate_rule_book_config_payload
from app.services.document_type_classifier import classify_document_type
from app.services.document_type_scoring_service import (
    compute_document_type_confidence,
    score_document_type_definition,
)
from app.services.invoice_data import InvoiceData, ParsedLineItem


def _invoice(**kwargs) -> Invoice:
    base = dict(id=1, tenant_id=1, status=InvoiceStatus.PARSING, currency="AUD")
    base.update(kwargs)
    return Invoice(**base)


def _parsed(**kwargs) -> InvoiceData:
    base = dict(
        vendor="Directus Cloud",
        invoice_no="INV-9",
        invoice_date=date(2026, 3, 1),
        total=Decimal("99.00"),
        line_items=[ParsedLineItem(description="SaaS", qty=Decimal("1"), amount=Decimal("99"))],
    )
    base.update(kwargs)
    return InvoiceData(**base)


def _dt03() -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code="DT-03",
        title="GRN (supporting)",
        shortTitle="GRN",
        klass="Supporting",
        posting="No",
        fraudRisk="low",
        oneLine="test",
        routeTarget="Purchase Management",
        requiredFields=["attachment_name"],
        absentFields=["invoice_no"],
        extractionFields=["attachment_name"],
        purchaseBundleRole="grn",
    )


def test_compute_confidence_blends_rule_fields_parse_and_heading() -> None:
    score = compute_document_type_confidence(
        rule_strength=1.0,
        field_completeness=1.0,
        parse_confidence="high",
        heading_alignment=1.0,
    )
    assert score == 1.0

    low_parse = compute_document_type_confidence(
        rule_strength=0.8,
        field_completeness=1.0,
        parse_confidence="low",
        heading_alignment=0.55,
    )
    assert low_parse == pytest.approx(0.805, abs=0.001)


def test_dt03_completeness_requires_attachment_name() -> None:
    definition = _dt03()
    invoice = _invoice(email_attachment_name="grn-delivery.pdf")
    parsed = _parsed(po_reference=None, invoice_no=None)
    breakdown = score_document_type_definition(
        definition,
        invoice=invoice,
        parsed=parsed,
        rule_strength=1.0,
        parse_confidence="high",
    )
    assert breakdown.field_completeness == 1.0
    assert breakdown.heading_alignment == pytest.approx(0.55, abs=0.001)
    assert breakdown.confidence == pytest.approx(0.955, abs=0.001)


def test_dt03_missing_attachment_name_lowers_confidence() -> None:
    definition = _dt03()
    invoice = _invoice(email_attachment_name="")
    parsed = _parsed(invoice_no=None)
    breakdown = score_document_type_definition(
        definition,
        invoice=invoice,
        parsed=parsed,
        rule_strength=1.0,
        parse_confidence="high",
    )
    assert "attachment_name" in breakdown.required_missing
    assert breakdown.confidence < 0.9


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
    assert result.score_breakdown is not None
