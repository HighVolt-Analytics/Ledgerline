"""Tests for classifier catalogue compiler."""

from __future__ import annotations

from app.schemas.document_type import DocumentTypeClassifier, DocumentTypeDefinition
from app.services.classifier_catalogue_compiler import (
    compile_catalogue_recognition,
    compile_recognition_rules_text,
)


def _custom_dt() -> DocumentTypeDefinition:
    return DocumentTypeDefinition.model_validate(
        {
            "code": "DT-99",
            "title": "Handwritten GRN",
            "shortTitle": "GRN",
            "klass": "Supporting",
            "posting": "No",
            "fraudRisk": "low",
            "oneLine": "Warehouse goods received note",
            "llmHint": "Often handwritten",
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
                            "field": "has_heading_grn",
                            "operator": "equals",
                            "value": "true",
                        },
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


def test_compile_recognition_rules_text() -> None:
    defn = _custom_dt()
    text = compile_recognition_rules_text(defn.classifier)
    assert "GRN" in text
    assert "GRN / delivery heading" in text


def test_compile_catalogue_recognition_merges_hint() -> None:
    defn = _custom_dt()
    merged = compile_catalogue_recognition(defn)
    assert "Match rules" in merged
    assert "handwritten" in merged.lower()
