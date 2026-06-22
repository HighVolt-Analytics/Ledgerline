"""Compute document-type confidence from rule match, field completeness, and parse quality."""

from __future__ import annotations

from dataclasses import dataclass

from collections.abc import Sequence

from app.models.invoice import Invoice
from app.schemas.document_type import DocumentTypeDefinition
from app.services.document_type_field_checks import field_is_absent, field_is_present
from app.services.document_type_playbook_service import (
    effective_absent_fields,
    effective_required_fields,
)
from app.services.document_type_rule_engine import (
    DocumentClassifierContext,
    build_document_classifier_context,
)
from app.services.document_heading_utils import (
    extract_document_heading_signals,
    heading_alignment_score,
)
from app.services.document_type_conflicts import (
    conflict_confidence_penalty,
    detect_signal_conflicts,
)
from app.services.invoice_data import InvoiceData, ParseConfidence

WEIGHT_RULE = 0.45
CONFIDENCE_TIE_EPSILON = 0.02
WEIGHT_FIELDS = 0.30
WEIGHT_PARSE = 0.15
WEIGHT_HEADING = 0.10


@dataclass(frozen=True)
class DocumentTypeScoreBreakdown:
    rule_strength: float
    field_completeness: float
    parse_score: float
    heading_alignment: float
    confidence: float
    required_present: list[str]
    required_missing: list[str]
    absent_ok: list[str]
    absent_violations: list[str]
    signal_conflicts: list[str]
    min_route_confidence: float


def parse_quality_score(parse_confidence: ParseConfidence | None) -> float:
    return 1.0 if parse_confidence == "high" else 0.6


def effective_min_route_confidence(definition: DocumentTypeDefinition) -> float:
    return float(definition.min_route_confidence)


def score_field_completeness(
    definition: DocumentTypeDefinition,
    *,
    invoice: Invoice,
    parsed: InvoiceData,
    ctx: DocumentClassifierContext,
) -> tuple[float, list[str], list[str], list[str], list[str]]:
    required = effective_required_fields(definition)
    absent = effective_absent_fields(definition)
    checks: list[bool] = []
    required_present: list[str] = []
    required_missing: list[str] = []
    absent_ok: list[str] = []
    absent_violations: list[str] = []

    for key in required:
        ok = field_is_present(key, invoice=invoice, parsed=parsed, ctx=ctx)
        checks.append(ok)
        if ok:
            required_present.append(key)
        else:
            required_missing.append(key)

    for key in absent:
        ok = field_is_absent(key, invoice=invoice, parsed=parsed, ctx=ctx)
        checks.append(ok)
        if ok:
            absent_ok.append(key)
        else:
            absent_violations.append(key)

    if not checks:
        return 1.0, required_present, required_missing, absent_ok, absent_violations
    return sum(checks) / len(checks), required_present, required_missing, absent_ok, absent_violations


def compute_document_type_confidence(
    *,
    rule_strength: float,
    field_completeness: float,
    parse_confidence: ParseConfidence | None,
    heading_alignment: float,
) -> float:
    parse_score = parse_quality_score(parse_confidence)
    blended = (
        WEIGHT_RULE * rule_strength
        + WEIGHT_FIELDS * field_completeness
        + WEIGHT_PARSE * parse_score
        + WEIGHT_HEADING * heading_alignment
    )
    return round(min(1.0, max(0.0, blended)), 4)


def score_document_type_definition(
    definition: DocumentTypeDefinition,
    *,
    invoice: Invoice,
    parsed: InvoiceData,
    rule_strength: float,
    parse_confidence: ParseConfidence | None,
    ctx: DocumentClassifierContext | None = None,
) -> DocumentTypeScoreBreakdown:
    context = ctx or build_document_classifier_context(invoice=invoice, parsed=parsed)
    field_score, req_present, req_missing, abs_ok, abs_bad = score_field_completeness(
        definition,
        invoice=invoice,
        parsed=parsed,
        ctx=context,
    )
    heading_signals = extract_document_heading_signals(context.document_text)
    if context.document_heading and not heading_signals.primary_label:
        heading_signals = extract_document_heading_signals(
            f"{context.document_heading}\n{context.document_text}"
        )
    heading_score = heading_alignment_score(
        definition.code,
        heading_signals,
        document_text=context.document_text,
        definition=definition,
    )
    conflicts = detect_signal_conflicts(context)
    confidence = compute_document_type_confidence(
        rule_strength=rule_strength,
        field_completeness=field_score,
        parse_confidence=parse_confidence,
        heading_alignment=heading_score,
    )
    confidence = round(
        max(0.0, confidence - conflict_confidence_penalty(conflicts)),
        4,
    )
    return DocumentTypeScoreBreakdown(
        rule_strength=rule_strength,
        field_completeness=round(field_score, 4),
        parse_score=parse_quality_score(parse_confidence),
        heading_alignment=round(heading_score, 4),
        confidence=confidence,
        required_present=req_present,
        required_missing=req_missing,
        absent_ok=abs_ok,
        absent_violations=abs_bad,
        signal_conflicts=conflicts,
        min_route_confidence=effective_min_route_confidence(definition),
    )


def _candidate_rank_key(
    item: tuple[DocumentTypeDefinition, DocumentTypeScoreBreakdown, str],
) -> tuple[float, int, float, int, int, int]:
    definition, breakdown, _source = item
    return (
        breakdown.confidence,
        -definition.classifier.priority,
        breakdown.field_completeness,
        -len(breakdown.absent_violations),
        -len(breakdown.required_missing),
        -len(breakdown.signal_conflicts),
    )


def pick_best_scored_definition(
    candidates: Sequence[tuple[DocumentTypeDefinition, DocumentTypeScoreBreakdown, str]],
) -> tuple[DocumentTypeDefinition, DocumentTypeScoreBreakdown, str] | None:
    if not candidates:
        return None
    best_confidence = max(item[1].confidence for item in candidates)
    near_best = [
        item
        for item in candidates
        if item[1].confidence >= best_confidence - CONFIDENCE_TIE_EPSILON
    ]
    pool = near_best if len(near_best) > 1 else list(candidates)
    return max(pool, key=_candidate_rank_key)
