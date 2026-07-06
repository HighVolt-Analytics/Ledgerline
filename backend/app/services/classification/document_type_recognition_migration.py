"""Migrate and sync document-type recognition (signals vs prompt)."""

from __future__ import annotations

from typing import Any, Literal

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_classifier_builder import (
    build_classifier_from_signals,
)
from app.services.classification.recognition_signal_registry import SIGNAL_CONDITIONS

RecognitionMode = Literal["signals", "prompt"]


def _condition_matches_signal(condition: dict[str, Any], signal_id: str) -> bool:
    spec = SIGNAL_CONDITIONS.get(signal_id)
    if spec is None:
        return False
    return (
        str(condition.get("field") or "") == str(spec.get("field") or "")
        and str(condition.get("operator") or "") == str(spec.get("operator") or "")
        and str(condition.get("value") or "") == str(spec.get("value") or "")
    )


def _collect_conditions(node: dict[str, Any]) -> list[dict[str, Any]]:
    if node.get("type") == "condition":
        return [node]
    if node.get("type") == "group":
        leaves: list[dict[str, Any]] = []
        for child in node.get("children") or []:
            if isinstance(child, dict):
                leaves.extend(_collect_conditions(child))
        return leaves
    return []


def parse_signals_from_classifier(root: dict[str, Any] | None) -> list[str]:
    """Best-effort recovery of recognition signal ids from a stored classifier tree."""
    if not isinstance(root, dict):
        return []
    leaves = _collect_conditions(root)
    found: list[str] = []
    for signal_id in SIGNAL_CONDITIONS:
        if any(_condition_matches_signal(leaf, signal_id) for leaf in leaves):
            found.append(signal_id)
    return found


def _legacy_prompt_parts(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("llm_prompt", "llmPrompt", "llm_hint", "llmHint", "one_line", "oneLine"):
        token = str(row.get(key) or "").strip()
        if token and token not in parts:
            parts.append(token)
    return "\n".join(parts).strip()


def migrate_document_type_recognition_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize one document type dict from legacy shape to signals/prompt model."""
    if not isinstance(row, dict):
        return row

    out = dict(row)
    llm_prompt = str(out.get("llm_prompt") or out.get("llmPrompt") or "").strip()
    if not llm_prompt:
        llm_prompt = _legacy_prompt_parts(out)

    recognition_signals = out.get("recognition_signals") or out.get("recognitionSignals") or []
    if not isinstance(recognition_signals, list):
        recognition_signals = []
    recognition_signals = [
        str(item).strip()
        for item in recognition_signals
        if str(item).strip() in SIGNAL_CONDITIONS
    ]

    mode_raw = str(out.get("recognition_mode") or out.get("recognitionMode") or "").strip().lower()
    if mode_raw not in {"signals", "prompt"}:
        classifier = out.get("classifier") if isinstance(out.get("classifier"), dict) else {}
        root = classifier.get("root") if isinstance(classifier, dict) else {}
        if not recognition_signals and isinstance(root, dict):
            recognition_signals = parse_signals_from_classifier(root)
        classifier_enabled = bool(classifier.get("enabled")) if isinstance(classifier, dict) else False
        has_classifier_children = bool(
            isinstance(root, dict) and (root.get("children") or [])
        )
        if recognition_signals or (classifier_enabled and has_classifier_children):
            mode_raw = "signals"
        elif llm_prompt:
            mode_raw = "prompt"
        else:
            mode_raw = "signals"

    recognition_mode: RecognitionMode = "prompt" if mode_raw == "prompt" else "signals"

    for legacy_key in (
        "one_line",
        "oneLine",
        "llm_hint",
        "llmHint",
        "classifier_customized",
        "classifierCustomized",
    ):
        out.pop(legacy_key, None)

    out["recognition_mode"] = recognition_mode
    out["recognition_signals"] = recognition_signals
    out["llm_prompt"] = llm_prompt if recognition_mode == "prompt" else ""
    return out


def sync_classifier_from_recognition(defn: DocumentTypeDefinition) -> DocumentTypeDefinition:
    """Compile recognition signals to classifier.root or disable classifier for prompt mode."""
    mode = (defn.recognition_mode or "signals").strip().lower()
    signals = [s for s in (defn.recognition_signals or []) if s in SIGNAL_CONDITIONS]

    if mode == "prompt":
        classifier = defn.classifier.model_copy(
            update={
                "enabled": False,
                "root": {"type": "group", "operator": "AND", "children": []},
            }
        )
        return defn.model_copy(update={"classifier": classifier, "recognition_signals": []})

    if not signals:
        root = defn.classifier.root if isinstance(defn.classifier.root, dict) else {}
        children = root.get("children") if isinstance(root, dict) else []
        if defn.classifier.enabled and children:
            return defn.model_copy(
                update={
                    "recognition_signals": signals,
                    "llm_prompt": "",
                    "recognition_mode": "signals",
                }
            )

    compiled = build_classifier_from_signals(
        signals,
        "grouped",
        priority=defn.classifier.priority or 100,
        confidence=defn.classifier.confidence or 0.85,
        enabled=bool(signals),
    )
    return defn.model_copy(
        update={
            "classifier": compiled,
            "recognition_signals": signals,
            "llm_prompt": "",
            "recognition_mode": "signals",
        }
    )


def migrate_document_type_recognition(defn: DocumentTypeDefinition) -> DocumentTypeDefinition:
    """Migrate a validated model (legacy extra fields already stripped at dict layer)."""
    row = migrate_document_type_recognition_row(defn.model_dump(by_alias=True))
    migrated = DocumentTypeDefinition.model_validate(row)
    return sync_classifier_from_recognition(migrated)


def migrate_document_types_recognition(data: dict[str, Any]) -> dict[str, Any]:
    """Apply recognition migration to all document_types in a rule-book payload dict."""
    types = data.get("document_types")
    if not isinstance(types, list):
        return data
    merged: list[Any] = []
    for row in types:
        if not isinstance(row, dict):
            merged.append(row)
            continue
        migrated_row = migrate_document_type_recognition_row(row)
        try:
            defn = DocumentTypeDefinition.model_validate(migrated_row)
            synced = sync_classifier_from_recognition(defn)
            merged.append(synced.model_dump(by_alias=True))
        except Exception:
            merged.append(migrated_row)
    data["document_types"] = merged
    return data
