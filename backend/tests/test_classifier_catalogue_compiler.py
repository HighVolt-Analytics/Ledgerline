"""Tests for classifier catalogue compiler and LLM catalogue rows."""

from __future__ import annotations

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.classifier_catalogue_compiler import (
    compile_catalogue_recognition,
    compile_recognition_rules_text,
)
from app.services.extraction.llm_catalogue_rows import build_llm_catalogue_rows


def _custom_dt() -> DocumentTypeDefinition:
    return DocumentTypeDefinition.model_validate(
        {
            "code": "DT-99",
            "title": "Handwritten GRN",
            "shortTitle": "GRN",
            "klass": "Non-transactional",
            "posting": "No",
            "recognition_mode": "signals",
            "recognition_signals": ["heading_grn", "text_grn"],
            "llm_prompt": "Often handwritten warehouse goods received note",
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


def test_compile_catalogue_recognition_merges_prompt() -> None:
    defn = _custom_dt()
    merged = compile_catalogue_recognition(defn)
    assert "Match rules" in merged
    assert "handwritten" in merged.lower()


def test_build_llm_catalogue_rows_signals_mode() -> None:
    defn = _custom_dt()
    rows = build_llm_catalogue_rows([defn])
    assert len(rows) == 1
    row = rows[0]
    assert row["code"] == "DT-99"
    assert row["recognition_mode"] == "signals"
    assert "recognition_rules" in row
    assert "Match rules" in row["recognition_rules"]
    assert "one_line" not in row
    assert "llm_hint" not in row


def test_build_llm_catalogue_rows_prompt_mode() -> None:
    defn = _custom_dt().model_copy(
        update={
            "recognition_mode": "prompt",
            "recognition_signals": [],
            "llm_prompt": "Custom permit letter from customs broker",
        }
    )
    rows = build_llm_catalogue_rows([defn])
    assert rows[0]["recognition_mode"] == "prompt"
    assert rows[0]["llm_prompt"] == "Custom permit letter from customs broker"
    assert "recognition_signals" not in rows[0]
