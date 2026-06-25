"""Classify uploaded samples against the org document-type catalogue."""

from __future__ import annotations

from dataclasses import dataclass

from collections.abc import Sequence

from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.rule_book_config import DocumentClassificationConfig
from typing import Any

from app.services.document_type_classifier import (
    CONFIG_RULE_STRENGTH,
    DocumentTypeClassification,
    classify_document_type,
    classification_audit_detail,
    rank_document_type_candidates,
)
from app.services.document_type_conflicts import detect_signal_conflicts
from app.services.document_type_rule_engine import (
    _document_field,
    build_document_classifier_context,
)
from app.services.document_type_sample_analyzer import ParsedDocumentSample, _parse_sample
from app.services.document_type_scoring_service import score_document_type_definition
from app.services.invoice_data import ParseConfidence
from app.services.rule_engine import eval_condition_group_generic


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


def _eval_classifier_root(root: dict[str, Any], ctx: object) -> bool:
    return eval_condition_group_generic(
        root,
        field_resolver=lambda field, _ctx=ctx: _document_field(_ctx, field),
    )


def _supporting_doc_identity_subtree(root: dict[str, Any]) -> dict[str, Any] | None:
    """First child of supporting_doc AND tree (identity OR-group before invoice guards)."""
    if root.get("operator") != "AND":
        return None
    children = root.get("children") or []
    if len(children) < 3:
        return None
    identity = children[0]
    return identity if isinstance(identity, dict) else None


def proposed_classifier_matches_sample(
    proposed_draft: DocumentTypeDefinition,
    sample: ParsedDocumentSample,
) -> bool:
    """True when the sample satisfies the proposed draft classifier (identity-only for supporting_doc)."""
    classifier = proposed_draft.classifier
    if not classifier.enabled:
        return False
    ctx = build_document_classifier_context(invoice=sample.invoice, parsed=sample.parsed)
    root = classifier.root
    if _eval_classifier_root(root, ctx):
        return True
    identity = _supporting_doc_identity_subtree(root)
    if identity is not None:
        return _eval_classifier_root(identity, ctx)
    return False


def classify_parsed_sample_for_proposal_preview(
    sample: ParsedDocumentSample,
    *,
    document_types: Sequence[DocumentTypeDefinition],
    proposed_draft: DocumentTypeDefinition,
    unclassified: DocumentClassificationConfig | None = None,
    expected_code: str | None = None,
) -> ClassifyPreviewResult:
    """Catalogue preview for sample analysis: gate Apply on proposed classifier, not catalogue winner."""
    base = classify_parsed_sample_against_catalog(
        sample,
        document_types=document_types,
        unclassified=unclassified,
        expected_code=expected_code,
    )
    expected = (expected_code or "").strip().upper()
    if not expected:
        return base

    proposed_match = proposed_classifier_matches_sample(proposed_draft, sample)
    if not proposed_match:
        return ClassifyPreviewResult(
            filename=base.filename,
            routed_code=base.routed_code,
            routed_confidence=base.routed_confidence,
            needs_review=base.needs_review,
            reason=base.reason,
            conflicts=base.conflicts,
            alternatives=base.alternatives,
            matches_expected=False,
        )

    parse_confidence = _parse_confidence(sample.confidence)
    ctx = build_document_classifier_context(invoice=sample.invoice, parsed=sample.parsed)
    breakdown = score_document_type_definition(
        proposed_draft,
        invoice=sample.invoice,
        parsed=sample.parsed,
        rule_strength=CONFIG_RULE_STRENGTH,
        parse_confidence=parse_confidence,
        ctx=ctx,
    )
    min_conf = proposed_draft.min_route_confidence or 0.65
    return ClassifyPreviewResult(
        filename=base.filename,
        routed_code=expected,
        routed_confidence=breakdown.confidence,
        needs_review=breakdown.confidence < min_conf,
        reason="Proposed classifier matches sample",
        conflicts=base.conflicts,
        alternatives=base.alternatives,
        matches_expected=True,
    )


def classify_parsed_samples_for_proposal_preview(
    parsed_samples: Sequence[ParsedDocumentSample],
    *,
    document_types: Sequence[DocumentTypeDefinition],
    proposed_draft: DocumentTypeDefinition,
    unclassified: DocumentClassificationConfig | None = None,
    expected_code: str | None = None,
) -> list[ClassifyPreviewResult]:
    results: list[ClassifyPreviewResult] = []
    for sample in parsed_samples:
        try:
            results.append(
                classify_parsed_sample_for_proposal_preview(
                    sample,
                    document_types=document_types,
                    proposed_draft=proposed_draft,
                    unclassified=unclassified,
                    expected_code=expected_code,
                )
            )
        except Exception:
            continue
    return results


def classify_parsed_sample_against_catalog(
    sample: ParsedDocumentSample,
    *,
    document_types: Sequence[DocumentTypeDefinition],
    unclassified: DocumentClassificationConfig | None = None,
    expected_code: str | None = None,
) -> ClassifyPreviewResult:
    parse_confidence = _parse_confidence(sample.confidence)
    ctx = build_document_classifier_context(invoice=sample.invoice, parsed=sample.parsed)
    conflicts = detect_signal_conflicts(ctx)

    result = classify_document_type(
        invoice=sample.invoice,
        parsed=sample.parsed,
        document_types=document_types,
        parse_confidence=parse_confidence,
        unclassified=unclassified,
    )

    ranked = rank_document_type_candidates(
        document_types=document_types,
        invoice=sample.invoice,
        parsed=sample.parsed,
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
        filename=sample.filename,
        routed_code=result.code,
        routed_confidence=result.confidence,
        needs_review=result.needs_review or bool(conflicts),
        reason=result.reason,
        conflicts=conflicts,
        alternatives=alternatives,
        matches_expected=matches_expected,
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
    return classify_parsed_sample_against_catalog(
        ParsedDocumentSample(
            filename=filename,
            invoice=invoice,
            parsed=parsed,
            confidence=parse_confidence_raw,
        ),
        document_types=document_types,
        unclassified=unclassified,
        expected_code=expected_code,
    )


def classify_parsed_samples_against_catalog(
    parsed_samples: Sequence[ParsedDocumentSample],
    *,
    document_types: Sequence[DocumentTypeDefinition],
    unclassified: DocumentClassificationConfig | None = None,
    expected_code: str | None = None,
) -> list[ClassifyPreviewResult]:
    results: list[ClassifyPreviewResult] = []
    for sample in parsed_samples:
        try:
            results.append(
                classify_parsed_sample_against_catalog(
                    sample,
                    document_types=document_types,
                    unclassified=unclassified,
                    expected_code=expected_code,
                )
            )
        except Exception:
            continue
    return results


def classify_samples_against_catalog(
    files: list[tuple[str, bytes]],
    *,
    document_types: Sequence[DocumentTypeDefinition],
    unclassified: DocumentClassificationConfig | None = None,
    expected_code: str | None = None,
    parsed_samples: Sequence[ParsedDocumentSample] | None = None,
) -> list[ClassifyPreviewResult]:
    if parsed_samples is not None:
        return classify_parsed_samples_against_catalog(
            parsed_samples,
            document_types=document_types,
            unclassified=unclassified,
            expected_code=expected_code,
        )
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
