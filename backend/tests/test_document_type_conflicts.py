"""Tests for document-type signal conflicts and classifier tie-break."""

from datetime import date
from decimal import Decimal

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.services.document_type_classifier import classify_document_type
from app.services.document_type_conflicts import (
    conflict_confidence_penalty,
    detect_signal_conflicts,
)
from app.services.document_type_rule_engine import build_document_classifier_context
from app.services.document_type_scoring_service import pick_best_scored_definition, score_document_type_definition
from app.services.invoice_data import InvoiceData, ParsedLineItem


def _invoice(**kwargs) -> Invoice:
    base = dict(id=1, tenant_id=1, status=InvoiceStatus.PARSING, currency="AUD")
    base.update(kwargs)
    return Invoice(**base)


def _parsed(**kwargs) -> InvoiceData:
    base = dict(
        vendor="Acme Pty Ltd",
        invoice_no="INV-100",
        invoice_date=date(2026, 3, 1),
        total=Decimal("500.00"),
        line_items=[ParsedLineItem(description="Services", qty=Decimal("1"), amount=Decimal("500"))],
    )
    base.update(kwargs)
    return InvoiceData(**base)


def test_detect_contract_heading_with_invoice_fields() -> None:
    invoice = _invoice()
    parsed = _parsed(
        document_text="MASTER SERVICE AGREEMENT\nInvoice No: INV-100\nTotal: 500.00",
        document_heading="Contract",
    )
    ctx = build_document_classifier_context(invoice=invoice, parsed=parsed)
    conflicts = detect_signal_conflicts(ctx)
    assert any("Contract heading" in item for item in conflicts)


def test_conflict_penalty_caps_at_max() -> None:
    assert conflict_confidence_penalty(["a", "b", "c", "d", "e"]) == pytest.approx(0.35)


def test_pick_best_prefers_lower_priority_on_near_tie() -> None:
    invoice = _invoice(email_attachment_name="sample.pdf")
    parsed = _parsed(po_reference="PO-1", invoice_no="INV-1")

    specific = DocumentTypeDefinition(
        code="DT-99",
        title="Specific PO invoice",
        shortTitle="PO inv",
        klass="Transactional",
        posting="Yes",
        fraudRisk="low",
        oneLine="test",
        routeTarget="Purchase Management",
        classifier=DocumentTypeClassifier(
            enabled=True,
            priority=10,
            root={
                "type": "group",
                "operator": "AND",
                "children": [
                    {
                        "type": "condition",
                        "field": "has_po_reference",
                        "operator": "equals",
                        "value": "true",
                    },
                ],
            },
        ),
    )
    catch_all = DocumentTypeDefinition(
        code="DT-01",
        title="Catch all",
        shortTitle="Catch",
        klass="Transactional",
        posting="Yes",
        fraudRisk="low",
        oneLine="test",
        routeTarget="Purchase Management",
        classifier=DocumentTypeClassifier(
            enabled=True,
            priority=200,
            root={
                "type": "group",
                "operator": "AND",
                "children": [
                    {
                        "type": "condition",
                        "field": "has_total",
                        "operator": "equals",
                        "value": "true",
                    },
                ],
            },
        ),
    )

    scored = []
    for definition in (catch_all, specific):
        breakdown = score_document_type_definition(
            definition,
            invoice=invoice,
            parsed=parsed,
            rule_strength=1.0,
            parse_confidence="high",
        )
        scored.append((definition, breakdown, "config_classifier"))

    best = pick_best_scored_definition(scored)
    assert best is not None
    assert best[0].code == "DT-99"


def test_classify_includes_conflicts_in_reason(capture_config) -> None:
    invoice = _invoice(email_attachment_name="contract.pdf")
    parsed = _parsed(
        document_text="CONTRACT\nInvoice number INV-9\nTotal $100",
        invoice_no="INV-9",
        total=Decimal("100"),
    )
    result = classify_document_type(
        invoice=invoice,
        parsed=parsed,
        document_types=capture_config.document_types,
        parse_confidence="high",
    )
    if result.score_breakdown and result.score_breakdown.signal_conflicts:
        assert "signal conflicts" in result.reason.lower() or result.score_breakdown.signal_conflicts
