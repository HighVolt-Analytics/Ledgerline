
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Routing review gate helpers."""

import json
from pathlib import Path

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.rule_book_config import validate_rule_book_config_payload
from app.services.account_mapper import MappingDetail
from app.services.document_type_classifier import DocumentTypeClassification
from app.services.routing_review_service import (
    classification_unmatched,
    requires_classification_review,
    requires_gl_mapping_review,
    requires_routing_review,
    routing_target_missing,
)
from app.services.rule_book_mapper import FALLBACK_RULE_TYPE


@pytest.fixture
def document_types():
    template = Path(__file__).resolve().parent / "fixtures" / "rule_book_demo.json"
    config = validate_rule_book_config_payload(json.loads(template.read_text(encoding="utf-8")))
    return list(config.document_types)


def test_routing_target_missing() -> None:
    inv = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.VALIDATING, route_target=None)
    assert routing_target_missing(inv) is True
    inv.route_target = "Purchase Management"
    assert routing_target_missing(inv) is False


def test_requires_classification_review_when_unclassified() -> None:
    inv = Invoice(tenant_id=TESTING_TENANT_UUID, status=InvoiceStatus.VALIDATING, route_target=None)
    classification = DocumentTypeClassification(
        "",
        0.44,
        "No classifier matched in rule book catalogue",
        min_route_confidence=0.85,
    )
    assert classification_unmatched(classification)
    assert requires_classification_review(inv, classification) is True
    assert requires_routing_review(inv, classification) is True


def test_requires_gl_mapping_review_for_posting_fallback_only() -> None:
    from app.schemas.document_type import DocumentTypeDefinition

    posting_dt = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-03",
            "title": "Tax Invoice",
            "shortTitle": "Tax",
            "klass": "Transactional",
            "posting": "Yes",
            "fraudRisk": "low",
            "oneLine": "x",
            "routeTarget": "Purchase Management",
            "enabled": True,
        }
    )
    non_posting_dt = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-16",
            "title": "Bank",
            "shortTitle": "Bank",
            "klass": "Reconciliation",
            "posting": "No",
            "fraudRisk": "low",
            "oneLine": "x",
            "routeTarget": "Vault",
            "enabled": True,
        }
    )
    document_types = [posting_dt, non_posting_dt]
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.MAPPING,
        document_type_code="DT-03",
        route_target="Expenses Management",
    )
    fallback = MappingDetail(
        expense_category="Suspense Account",
        account_code="9999",
        account_name="Suspense Account",
        rule_type=FALLBACK_RULE_TYPE,
        match_reason="No rule matched",
    )
    assert requires_gl_mapping_review(inv, fallback, document_types=document_types) is True

    inv.document_type_code = "DT-16"
    assert requires_gl_mapping_review(inv, fallback, document_types=document_types) is False
