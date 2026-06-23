"""Classify uploaded samples against the org document-type catalogue."""

from __future__ import annotations

from dataclasses import dataclass

from collections.abc import Sequence

from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.rule_book_config import DocumentClassificationConfig
from app.services.document_type_classifier import (
    DocumentTypeClassification,
    classify_document_type,
    classification_audit_detail,
    rank_document_type_candidates,
)
from app.services.document_type_conflicts import detect_signal_conflicts
from app.services.document_type_rule_engine import build_document_classifier_context
from app.services.document_type_sample_analyzer import _parse_sample
from app.services.invoice_data import ParseConfidence


@dataclass(frozen=True)
class ClassifyPreviewCandidate:
    code: str
    confidence: float
    reason: str
    needs_review: bool
    priority: int


@dataclass(frozen=True)
class ClassifyPreviewResult:
    filename: str
    routed_code: str
    routed_confidence: float
    needs_review: bool
    reason: str
    conflicts: list[str]
    alternatives: list[ClassifyPreviewCandidate]
    matches_expected: bool | None


def merge_draft_document_type(
    document_types: Sequence[DocumentTypeDefinition],
    draft: DocumentTypeDefinition | None,
) -> list[DocumentTypeDefinition]:
    if draft is None:
        return list(document_types)
    code = draft.code.strip().upper()
    merged = [item for item in document_types if item.code.strip().upper() != code]
    merged.append(draft)
    return merged


def _parse_confidence(value: str | None) -> ParseConfidence | None:
    if value in {"high", "low"}:
        return value
    return "low"


def _candidate_from_classification(
    result: DocumentTypeClassification,
    *,
    definition: DocumentTypeDefinition | None = None,
) -> ClassifyPreviewCandidate:
    priority = definition.classifier.priority if definition is not None else 999
    return ClassifyPreviewCandidate(
        code=result.code,
        confidence=result.confidence,
        reason=result.reason,
        needs_review=result.needs_review,
        priority=priority,
    )


def classify_sample_against_catalog(
    filename: str,
    content: bytes,
    *,
    document_types: Sequence[DocumentTypeDefinition],
    unclassified: DocumentClassificationConfig | None = None,
    expected_code: str | None = None,
) -> ClassifyPreviewResult:
    invoice, parsed, parse_confidence_raw = _parse_sample(filename, content)
    parse_confidence = _parse_confidence(parse_confidence_raw)
    ctx = build_document_classifier_context(invoice=invoice, parsed=parsed)
    conflicts = detect_signal_conflicts(ctx)

    result = classify_document_type(
        invoice=invoice,
        parsed=parsed,
        document_types=document_types,
        parse_confidence=parse_confidence,
        unclassified=unclassified,
    )

    ranked = rank_document_type_candidates(
        document_types=document_types,
        invoice=invoice,
        parsed=parsed,
        parse_confidence=parse_confidence,
        limit=5,
    )

    by_code = {item.code.strip().upper(): item for item in document_types}
    alternatives: list[ClassifyPreviewCandidate] = []
    seen: set[str] = set()
    for candidate in ranked:
        code = candidate.code.strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        definition = by_code.get(code)
        alternatives.append(
            _candidate_from_classification(candidate, definition=definition)
        )

    expected = (expected_code or "").strip().upper()
    matches_expected: bool | None = None
    if expected:
        matches_expected = result.code.strip().upper() == expected

    return ClassifyPreviewResult(
        filename=filename,
        routed_code=result.code,
        routed_confidence=result.confidence,
        needs_review=result.needs_review or bool(conflicts),
        reason=result.reason,
        conflicts=conflicts,
        alternatives=alternatives,
        matches_expected=matches_expected,
    )


def classify_samples_against_catalog(
    files: list[tuple[str, bytes]],
    *,
    document_types: Sequence[DocumentTypeDefinition],
    unclassified: DocumentClassificationConfig | None = None,
    expected_code: str | None = None,
) -> list[ClassifyPreviewResult]:
    results: list[ClassifyPreviewResult] = []
    for filename, content in files:
        try:
            results.append(
                classify_sample_against_catalog(
                    filename,
                    content,
                    document_types=document_types,
                    unclassified=unclassified,
                    expected_code=expected_code,
                )
            )
        except Exception:
            continue
    return results


def preview_result_to_dict(result: ClassifyPreviewResult) -> dict[str, object]:
    return {
        "filename": result.filename,
        "routed_code": result.routed_code,
        "routed_confidence": result.routed_confidence,
        "needs_review": result.needs_review,
        "reason": result.reason,
        "conflicts": result.conflicts,
        "matches_expected": result.matches_expected,
        "alternatives": [
            {
                "code": item.code,
                "confidence": item.confidence,
                "reason": item.reason,
                "needs_review": item.needs_review,
                "priority": item.priority,
            }
            for item in result.alternatives
        ],
    }


def classification_detail_for_preview(
    result: ClassifyPreviewResult,
    *,
    document_types: Sequence[DocumentTypeDefinition],
) -> dict[str, object]:
    classification = DocumentTypeClassification(
        result.routed_code,
        result.routed_confidence,
        result.reason,
    )
    detail = classification_audit_detail(
        classification,
        document_types=document_types,
    )
    detail["signal_conflicts"] = result.conflicts
    detail["alternatives"] = preview_result_to_dict(result)["alternatives"]
    return detail
