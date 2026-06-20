"""Document type (DT-xx) classification after OCR."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.rule_book_config import validate_rule_book_config_payload
from app.services.document_type_catalog import route_target_for_document_type
from app.services.document_type_classifier import classify_document_type
from app.services.invoice_data import InvoiceData, ParsedLineItem
from app.services.invoice_evaluation_service import (
    ROUTE_EXPENSES,
    ROUTE_PURCHASE,
    ROUTE_TEAM,
    ROUTE_VAULT,
    evaluate_invoice_routing,
)
from app.services.rule_book_mapper import clear_classification_config_cache


@pytest.fixture(autouse=True)
def _clear_catalog_cache() -> None:
    from app.services.document_type_catalog import clear_document_type_catalog_cache
    from app.services.document_type_classifier_templates import clear_classifier_templates_cache
    from app.services.document_type_field_defaults import clear_document_type_defaults_cache

    clear_document_type_catalog_cache()
    clear_classifier_templates_cache()
    clear_document_type_defaults_cache()
    yield
    clear_document_type_catalog_cache()
    clear_classifier_templates_cache()
    clear_document_type_defaults_cache()


def _invoice(**kwargs) -> Invoice:
    base = dict(
        id=1,
        org_id=1,
        status=InvoiceStatus.PARSING,
        currency="AUD",
    )
    base.update(kwargs)
    return Invoice(**base)


def _parsed(**kwargs) -> InvoiceData:
    base = dict(
        vendor="Acme Supplies Pty Ltd",
        invoice_no="INV-1001",
        invoice_date=date(2026, 3, 1),
        due_date=date(2026, 3, 31),
        subtotal=Decimal("100.00"),
        gst=Decimal("10.00"),
        total=Decimal("110.00"),
        po_reference="PO-44871",
        line_items=[ParsedLineItem(description="Office paper", qty=Decimal("10"), amount=Decimal("100"))],
    )
    base.update(kwargs)
    return InvoiceData(**base)


def test_classify_grn_filename(capture_config) -> None:
    result = classify_document_type(
        invoice=_invoice(email_attachment_name="GRN-PO-44871.pdf"),
        parsed=_parsed(invoice_no=None, due_date=None),
        document_types=capture_config.document_types,
    )
    assert result.code == "DT-03"
    assert result.route_confident
    assert result.confidence >= 0.85


def test_classify_po_filename(capture_config) -> None:
    result = classify_document_type(
        invoice=_invoice(email_attachment_name="PO-44871.pdf"),
        parsed=_parsed(invoice_no=None, due_date=None, po_reference="PO-44871"),
        document_types=capture_config.document_types,
    )
    assert result.code == "DT-02"
    assert result.confidence >= 0.85


def test_classify_po_goods_invoice(capture_config) -> None:
    result = classify_document_type(
        invoice=_invoice(email_attachment_name="INV-558210.pdf"),
        parsed=_parsed(),
        document_types=capture_config.document_types,
    )
    assert result.code == "DT-01"
    assert result.route_confident


def test_classify_non_po_vendor_invoice_purchase_fallback(capture_config) -> None:
    result = classify_document_type(
        invoice=_invoice(email_attachment_name="tax-invoice-mkt.pdf"),
        parsed=_parsed(po_reference=None),
        document_types=capture_config.document_types,
        parse_confidence="high",
    )
    assert result.code in {"DT-01", "DT-04", "DT-21"}
    assert result.confidence >= 0.65


def test_classify_quote_low_confidence(capture_config) -> None:
    result = classify_document_type(
        invoice=_invoice(email_attachment_name="quote-2026.pdf"),
        parsed=InvoiceData(document_text="Quotation for services"),
        document_types=capture_config.document_types,
    )
    assert result.code == "DT-24"
    assert result.route_confident
    assert result.confidence >= result.score_breakdown.min_route_confidence
    assert route_target_for_document_type(result.code, capture_config.document_types) == ROUTE_VAULT


def test_classify_team_claim_by_filename(capture_config) -> None:
    result = classify_document_type(
        invoice=_invoice(email_attachment_name="team-meal-claim.pdf", email_sender="random@x.com"),
        parsed=_parsed(po_reference=None, invoice_no="TE-001"),
        document_types=capture_config.document_types,
    )
    assert result.code == "DT-12"
    assert route_target_for_document_type(result.code, capture_config.document_types) == ROUTE_TEAM


def test_classify_contract_from_document_text(capture_config) -> None:
    body = (
        "CONTRACT FOR SPOT PURCHASE signed for and on behalf of SELLER "
        "governing law and jurisdiction NSW terms and conditions"
    )
    result = classify_document_type(
        invoice=_invoice(email_attachment_name="4752d7ef-d348-4433-8228-26da345ace96.pdf"),
        parsed=InvoiceData(document_text=body),
        document_types=capture_config.document_types,
        parse_confidence="high",
    )
    assert result.code == "DT-16"
    assert result.confidence >= 0.85


def test_route_target_follows_org_config(capture_config) -> None:
    custom = capture_config.model_copy(
        update={
            "document_types": [
                item.model_copy(
                    update={"route_target": "Vault" if item.code == "DT-03" else item.route_target}
                )
                for item in capture_config.document_types
            ]
        }
    )
    assert route_target_for_document_type("DT-03", custom.document_types) == ROUTE_VAULT


def test_routing_prefers_confident_document_type(capture_config) -> None:
    clear_classification_config_cache()
    assert route_target_for_document_type("DT-03", capture_config.document_types) == ROUTE_PURCHASE
    invoice = _invoice(
        document_type_code="DT-21",
        document_type_confidence=0.88,
        email_sender="billing@amazon.com",
        email_subject="AWS invoice",
        email_attachment_name="AWS-Invoice.pdf",
        vendor="Amazon Web Services",
        invoice_no="AWS-123",
        total=Decimal("250.00"),
        po_reference=None,
    )
    result = evaluate_invoice_routing(invoice, capture_config)
    assert result.route_target == ROUTE_EXPENSES
    assert "dt:DT-21" in result.matched_rule_ids


def test_routing_low_confidence_document_type_needs_review(capture_config) -> None:
    clear_classification_config_cache()
    invoice = _invoice(
        document_type_code="DT-24",
        document_type_confidence=0.45,
        vendor="Amazon Web Services",
        abn="98765432101",
        total=Decimal("10.00"),
    )
    result = evaluate_invoice_routing(invoice, capture_config)
    assert result.evaluation_status == "needs_review"


def test_unclassified_without_catalogue_type_returns_empty_code() -> None:
    from app.schemas.document_type import DocumentTypeDefinition
    from app.schemas.rule_book_config import DocumentClassificationConfig

    thin_catalogue = [
        DocumentTypeDefinition(
            code="DT-01",
            title="Invoice",
            shortTitle="Invoice",
            klass="Transactional",
            posting="Yes",
            fraudRisk="low",
            oneLine="test",
            routeTarget="Purchase Management",
        )
    ]
    result = classify_document_type(
        invoice=_invoice(email_attachment_name="misc.pdf"),
        parsed=InvoiceData(vendor="Unknown"),
        document_types=thin_catalogue,
        unclassified=DocumentClassificationConfig(unclassified_document_type_code="DT-24"),
    )
    assert result.code == ""
    assert "No classifier matched" in result.reason


def test_classify_invoice_heading_without_invoice_number() -> None:
    from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition

    catalogue = [
        DocumentTypeDefinition(
            code="DT-01",
            title="PO-based goods invoice",
            shortTitle="PO goods invoice",
            klass="Transactional",
            posting="Yes",
            fraudRisk="low",
            oneLine="3-way match invoice",
            routeTarget="Purchase Management",
            classifier=DocumentTypeClassifier(
                enabled=True,
                priority=50,
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
                        {
                            "type": "condition",
                            "field": "has_invoice_no",
                            "operator": "equals",
                            "value": "true",
                        },
                        {
                            "type": "condition",
                            "field": "has_total",
                            "operator": "equals",
                            "value": "true",
                        },
                    ],
                },
            ),
            extraction_fields=[
                "vendor",
                "invoice_no",
                "po_reference",
                "total",
                "line_items",
            ],
        ),
        DocumentTypeDefinition(
            code="DT-02",
            title="PO",
            shortTitle="PO",
            klass="Supporting",
            posting="No",
            fraudRisk="low",
            oneLine="PO",
            routeTarget="Purchase Management",
            purchaseBundleRole="po",
        ),
    ]
    result = classify_document_type(
        invoice=_invoice(
            purchase_document_type="invoice",
            document_text="TAX INVOICE\nAcme Corp\nPO-2025-0101",
        ),
        parsed=_parsed(invoice_no=None, total=Decimal("1242608.00")),
        document_types=catalogue,
    )
    assert result.code == "DT-01"
    assert result.confidence >= 0.65


def test_classify_purchase_kind_fallback_when_classifier_misses() -> None:
    from app.schemas.document_type import DocumentTypeDefinition

    catalogue = [
        DocumentTypeDefinition(
            code="DT-01",
            title="PO-based goods invoice",
            shortTitle="PO goods invoice",
            klass="Transactional",
            posting="Yes",
            fraudRisk="low",
            oneLine="3-way match invoice",
            routeTarget="Purchase Management",
            classifier={"enabled": False, "priority": 50, "confidence": 0.85, "root": {"type": "group", "operator": "AND", "children": []}},
            extraction_fields=["vendor", "total", "po_reference"],
        ),
        DocumentTypeDefinition(
            code="DT-03",
            title="GRN",
            shortTitle="GRN",
            klass="Supporting",
            posting="No",
            fraudRisk="low",
            oneLine="GRN",
            routeTarget="Purchase Management",
            purchaseBundleRole="grn",
            classifier={"enabled": False, "priority": 45, "confidence": 0.85, "root": {"type": "group", "operator": "AND", "children": []}},
        ),
    ]
    result = classify_document_type(
        invoice=_invoice(
            purchase_document_type="grn",
            document_text="GOODS RECEIPT NOTE\nPO-2025-0101",
        ),
        parsed=_parsed(invoice_no=None, total=None),
        document_types=catalogue,
    )
    assert result.code == "DT-03"
    assert "Purchase document role inferred" in result.reason


def test_effective_document_type_code_uses_purchase_role() -> None:
    from app.schemas.document_type import DocumentTypeDefinition
    from app.services.document_type_playbook_service import effective_document_type_code

    from tests.test_purchase_bundle_role import _grn_type, _po_type

    catalogue = [
        DocumentTypeDefinition(
            code="DT-01",
            title="Invoice",
            shortTitle="Invoice",
            klass="Transactional",
            posting="Yes",
            fraudRisk="low",
            oneLine="test",
            routeTarget="Purchase Management",
        ),
        _po_type(),
        _grn_type(),
    ]
    invoice = _invoice(document_type_code=None, purchase_document_type="grn")
    assert effective_document_type_code(invoice, catalogue) == "DT-03"
