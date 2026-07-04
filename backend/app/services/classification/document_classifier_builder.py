"""Build document-type classifier trees from recognition signals (parity with frontend)."""

from __future__ import annotations

from typing import Any

from app.schemas.document_type import DocumentTypeClassifier
from app.services.classification.recognition_signal_registry import (
    SIGNAL_CONDITIONS,
    SIGNAL_PICK_GROUPS,
    SUPPORTING_GUARDS,
    WEAK_SIGNAL_IDS,
    signal_condition,
)

RecognitionSignalId = str
ClassifierLayout = str

WEAK_SIGNALS = WEAK_SIGNAL_IDS
_SIGNAL_CONDITIONS = SIGNAL_CONDITIONS


def _cond(signal_id: RecognitionSignalId) -> dict[str, Any]:
    spec = signal_condition(signal_id)
    if spec is None:
        return {"type": "condition", "field": "document_text", "operator": "contains", "value": ""}
    return {"type": "condition", **spec}


def _or_group(children: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "group", "operator": "OR", "children": children}


def _and_group(children: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "group", "operator": "AND", "children": children}


def build_classifier_root_grouped(signal_ids: list[RecognitionSignalId]) -> dict[str, Any]:
    available = set(signal_ids)
    and_children: list[dict[str, Any]] = []
    used: set[RecognitionSignalId] = set()

    for group in SIGNAL_PICK_GROUPS:
        matched = [signal_id for signal_id in group if signal_id in available]
        if not matched:
            continue
        used.update(matched)
        if len(matched) == 1:
            and_children.append(_cond(matched[0]))
        else:
            and_children.append(_or_group([_cond(signal_id) for signal_id in matched]))

    ungrouped = [signal_id for signal_id in signal_ids if signal_id not in used and signal_id not in WEAK_SIGNALS]
    if len(ungrouped) == 1:
        and_children.append(_cond(ungrouped[0]))
    elif len(ungrouped) > 1:
        and_children.append(_or_group([_cond(signal_id) for signal_id in ungrouped]))

    for signal_id in signal_ids:
        if signal_id in WEAK_SIGNALS:
            and_children.append(_cond(signal_id))

    if not and_children:
        return {"type": "group", "operator": "AND", "children": []}
    return _and_group(and_children)


def build_classifier_root(signal_ids: list[RecognitionSignalId], layout: ClassifierLayout) -> dict[str, Any]:
    if not signal_ids:
        return {"type": "group", "operator": "AND", "children": []}

    if layout == "grouped":
        return build_classifier_root_grouped(signal_ids)

    leaves = [_cond(signal_id) for signal_id in signal_ids]
    if layout == "all_signals":
        return _and_group(leaves)
    if layout == "supporting_doc":
        identity = build_classifier_root_grouped(signal_ids)
        if identity.get("type") == "condition":
            identity = _or_group([identity])
        return _and_group([identity, *SUPPORTING_GUARDS])
    return _or_group(leaves)


def build_classifier_from_signals(
    signal_ids: list[RecognitionSignalId],
    layout: ClassifierLayout,
    *,
    priority: int = 100,
    confidence: float = 0.85,
    enabled: bool = True,
) -> DocumentTypeClassifier:
    return DocumentTypeClassifier(
        enabled=enabled and bool(signal_ids),
        priority=priority,
        confidence=confidence,
        root=build_classifier_root(signal_ids, layout),
    )


def eval_recognition_signal(ctx: object, signal_id: RecognitionSignalId) -> bool:
    """True when a single recognition signal's classifier condition matches the sample."""
    from app.services.classification.document_type_rule_engine import _document_field
    from app.services.rule_book.rule_engine import _match_value

    spec = signal_condition(signal_id)
    if spec is None:
        return False
    haystack = _document_field(ctx, str(spec["field"]))
    return _match_value(
        haystack,
        str(spec["operator"]),
        str(spec["value"]),
    )


def filter_verified_recognition_signals(
    ctx: object,
    signals: frozenset[RecognitionSignalId] | set[RecognitionSignalId],
) -> frozenset[RecognitionSignalId]:
    """Drop detection-only false positives before building a sample classifier."""
    verified = {signal_id for signal_id in signals if eval_recognition_signal(ctx, signal_id)}
    return frozenset(verified)
