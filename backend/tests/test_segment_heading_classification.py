"""Tests for heading-aware split PDF classification."""

from __future__ import annotations

from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.services.document_type_classifier import classify_document_type
from app.services.document_type_rule_engine import list_configured_document_type_matches
from app.services.invoice_data import InvoiceData
from app.services.segment_heading_classification import (
    classify_from_segment_heading,
    classifier_match_relies_on_invoice_number,
    filter_configured_matches_for_heading,
    score_document_type_for_heading,
)


def _dt(
    code: str,
    *,
    short_title: str,
    root: dict,
    priority: int = 50,
    route_target: str = "Vault",
    klass: str = "Informational",
    posting: str = "No",
) -> DocumentTypeDefinition:
    return DocumentTypeDefinition(
        code=code,
        title=short_title,
        shortTitle=short_title,
        klass=klass,
        posting=posting,
        fraudRisk="low",
        oneLine="test",
        routeTarget=route_target,
        enabled=True,
        classifier=DocumentTypeClassifier(enabled=True, priority=priority, root=root),
    )


def test_score_document_type_for_heading_matches_short_title_token() -> None:
    definition = _dt("DT-07", short_title="coo", root={"type": "group", "operator": "AND", "children": []})
    assert score_document_type_for_heading(definition, "certificate_of_origin") >= 0.95


def test_dt07_catchall_filtered_for_non_invoice_heading() -> None:
    catchall = _dt(
        "DT-07",
        short_title="coo",
        priority=100,
        root={
            "type": "group",
            "operator": "OR",
            "children": [
                {
                    "type": "condition",
                    "field": "has_invoice_no",
                    "operator": "equals",
                    "value": "true",
                }
            ],
        },
    )
    invoice = Invoice(
        tenant_id=1,
        status=InvoiceStatus.PENDING,
        currency="AUD",
        purchase_document_type="invoice",
        invoice_no="260671582",
        total=Decimal("1000"),
    )
    parsed = InvoiceData(
        invoice_no="260671582",
        total=Decimal("1000"),
        document_text="Shipment details\nInvoice No: 260671582",
    )
    assert classifier_match_relies_on_invoice_number(catchall, invoice=invoice, parsed=parsed)

    matches = list_configured_document_type_matches([catchall], invoice=invoice, parsed=parsed)
    assert matches
    filtered = filter_configured_matches_for_heading(
        matches,
        heading_kind="packing_list",
        invoice=invoice,
        parsed=parsed,
    )
    assert filtered == []


def test_certificate_of_origin_routes_to_coo_document_type() -> None:
    catchall = _dt(
        "DT-07",
        short_title="coo",
        priority=100,
        root={
            "type": "group",
            "operator": "OR",
            "children": [
                {
                    "type": "condition",
                    "field": "has_invoice_no",
                    "operator": "equals",
                    "value": "true",
                }
            ],
        },
    )
    purchase_invoice = _dt(
        "DT-01",
        short_title="PO goods invoice",
        route_target="Purchase Management",
        klass="Transactional",
        priority=180,
        root={
            "type": "group",
            "operator": "AND",
            "children": [
                {
                    "type": "condition",
                    "field": "has_invoice_no",
                    "operator": "equals",
                    "value": "true",
                }
            ],
        },
    )
    invoice = Invoice(
        tenant_id=1,
        status=InvoiceStatus.PENDING,
        currency="AUD",
        purchase_document_type="invoice",
        invoice_no="260671582",
        total=Decimal("1000"),
    )
    parsed = InvoiceData(
        invoice_no="260671582",
        total=Decimal("1000"),
        document_text="CERTIFICATE OF ORIGIN\nInvoice No: 260671582",
    )

    result = classify_from_segment_heading(
        heading_kind="certificate_of_origin",
        document_types=[catchall, purchase_invoice],
        invoice=invoice,
        parsed=parsed,
        parse_confidence="high",
    )
    assert result is not None
    assert result.code == "DT-07"


def test_commercial_invoice_prefers_purchase_invoice_mapping() -> None:
    catchall = _dt(
        "DT-07",
        short_title="coo",
        priority=100,
        root={
            "type": "group",
            "operator": "OR",
            "children": [
                {
                    "type": "condition",
                    "field": "has_invoice_no",
                    "operator": "equals",
                    "value": "true",
                }
            ],
        },
    )
    purchase_invoice = _dt(
        "DT-01",
        short_title="PO goods invoice",
        route_target="Purchase Management",
        klass="Transactional",
        posting="Yes",
        priority=180,
        root={
            "type": "group",
            "operator": "AND",
            "children": [
                {
                    "type": "condition",
                    "field": "has_invoice_no",
                    "operator": "equals",
                    "value": "true",
                }
            ],
        },
    )
    invoice = Invoice(
        tenant_id=1,
        status=InvoiceStatus.PENDING,
        currency="AUD",
        purchase_document_type="invoice",
        invoice_no="260671582",
        total=Decimal("1000"),
    )
    parsed = InvoiceData(
        invoice_no="260671582",
        total=Decimal("1000"),
        document_text="COMMERCIAL INVOICE\nInvoice No: 260671582\nTotal USD 1000",
    )

    result = classify_document_type(
        invoice=invoice,
        parsed=parsed,
        document_types=[catchall, purchase_invoice],
        parse_confidence="high",
        segment_heading_kind="commercial_invoice",
    )
    assert result.code == "DT-01"


def test_transport_doc_does_not_match_contract_type() -> None:
    contract = _dt(
        "DT-06",
        short_title="Contract / SOW",
        priority=20,
        root={
            "type": "group",
            "operator": "OR",
            "children": [
                {
                    "type": "condition",
                    "field": "document_text",
                    "operator": "contains",
                    "value": "terms and conditions",
                }
            ],
        },
    )
    invoice = Invoice(tenant_id=1, status=InvoiceStatus.PENDING, currency="AUD")
    parsed = InvoiceData(
        document_text="HAWB 1234567890\nTerms and conditions apply",
    )
    matches = list_configured_document_type_matches([contract], invoice=invoice, parsed=parsed)
    assert matches
    filtered = filter_configured_matches_for_heading(
        matches,
        heading_kind="transport_doc",
        invoice=invoice,
        parsed=parsed,
    )
    assert filtered == []
