"""Build LLM classification catalogue rows from document type definitions."""

from __future__ import annotations

from typing import Any, Sequence

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.classifier_catalogue_compiler import compile_recognition_rules_text
from app.services.classification.recognition_signal_registry import RECOGNITION_SIGNAL_CATALOG


def build_llm_catalogue_rows(
    document_types: Sequence[DocumentTypeDefinition],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for defn in document_types:
        if not defn.enabled:
            continue
        mode = (defn.recognition_mode or "signals").strip().lower()
        row: dict[str, Any] = {
            "code": defn.code.strip().upper(),
            "title": defn.title,
            "recognition_mode": "prompt" if mode == "prompt" else "signals",
        }
        if mode == "prompt":
            prompt = (defn.llm_prompt or "").strip()
            if prompt:
                row["llm_prompt"] = prompt
        else:
            rules = compile_recognition_rules_text(defn.classifier)
            if rules:
                row["recognition_rules"] = rules
            enriched: list[dict[str, str]] = []
            for signal_id in defn.recognition_signals or []:
                info = RECOGNITION_SIGNAL_CATALOG.get(signal_id)
                if info is None:
                    continue
                enriched.append(
                    {
                        "id": signal_id,
                        "label": info.label,
                        "hint": info.hint,
                    }
                )
            if enriched:
                row["recognition_signals"] = enriched
        rows.append(row)
    return rows
