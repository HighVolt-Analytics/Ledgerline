"""Tests for document type recognition test service."""

from __future__ import annotations

from app.schemas.document_type import DocumentTypeDefinition
from app.services.document_type_recognition_service import evaluate_document_type_recognition


def _grn_dt() -> DocumentTypeDefinition:
    return DocumentTypeDefinition.model_validate(
        {
            "code": "DT-99",
            "title": "GRN",
            "shortTitle": "GRN",
            "klass": "Supporting",
            "posting": "No",
            "fraudRisk": "low",
            "oneLine": "Goods received",
            "routeTarget": "Vault",
            "enabled": True,
            "classifier": {
                "enabled": True,
                "priority": 100,
                "confidence": 0.85,
                "root": {
                    "type": "group",
                    "operator": "OR",
                    "children": [
                        {
                            "type": "condition",
                            "field": "document_text",
                            "operator": "contains",
                            "value": "GRN",
                        },
                    ],
                },
            },
        }
    )


def test_recognition_test_matches_grn_text() -> None:
    result = evaluate_document_type_recognition(
        _grn_dt(),
        document_text="GRN PO 12345 received qty 10",
        document_heading="GOODS RECEIVED",
    )
    assert result.matches is True
    assert result.match_rules_passed is True


def test_recognition_test_single_and_condition() -> None:
    dt = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-88",
            "title": "Invoice",
            "shortTitle": "Invoice",
            "klass": "Transactional",
            "posting": "No",
            "fraudRisk": "low",
            "oneLine": "Tax invoice",
            "routeTarget": "Vault",
            "enabled": True,
            "classifier": {
                "enabled": True,
                "priority": 100,
                "confidence": 0.85,
                "root": {
                    "type": "group",
                    "operator": "AND",
                    "children": [
                        {
                            "type": "condition",
                            "field": "document_heading",
                            "operator": "contains",
                            "value": "tax invoice",
                        },
                    ],
                },
            },
        }
    )
    result = evaluate_document_type_recognition(
        dt,
        document_text="Line items and total",
        document_heading="TAX INVOICE",
    )
    assert result.matches is True
    assert result.match_rules_passed is True


def test_recognition_test_no_match() -> None:
    result = evaluate_document_type_recognition(
        _grn_dt(),
        document_text="Monthly bank statement only",
    )
    assert result.matches is False
