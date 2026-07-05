"""Classify parsed invoices to DT-xx codes from Rule Book config only."""

from __future__ import annotations

from dataclasses import dataclass

from collections.abc import Sequence

from app.models.invoice import Invoice
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.rule_book_config import DocumentClassificationConfig
from app.services.classification.document_type_catalog import (
    DOCUMENT_TYPE_ROUTE_CONFIDENCE_MIN,
    get_document_type_definition,
    min_route_confidence_for_document_type,
)
from app.services.classification.document_type_scoring_service import (
    DocumentTypeScoreBreakdown,
    pick_best_scored_definition,
    score_document_type_definition,
)
from app.services.classification.segment_heading_classification import (
    list_heading_aware_document_type_matches,
    resolve_segment_heading_kind,
)
from app.services.invoice.invoice_data import InvoiceData, ParseConfidence

CONFIG_RULE_STRENGTH = 1.0


@dataclass(frozen=True)
class DocumentTypeClassification:
    code: str
    confidence: float
    reason: str
    min_route_confidence: float = DOCUMENT_TYPE_ROUTE_CONFIDENCE_MIN
    score_breakdown: DocumentTypeScoreBreakdown | None = None

    @property
    def needs_review(self) -> bool:
        return self.confidence < self.min_route_confidence

    @property
    def route_confident(self) -> bool:
        return self.confidence >= self.min_route_confidence


def _gate_classification(
    result: DocumentTypeClassification,
    document_types: Sequence[DocumentTypeDefinition] | None,
) -> DocumentTypeClassification:
    if not document_types:
        return result
    definition = get_document_type_definition(result.code, document_types=document_types)
    min_conf = min_route_confidence_for_document_type(result.code, document_types)
    if definition is None:
        return DocumentTypeClassification(
            result.code,
            min(result.confidence, min_conf - 0.01),
            f"{result.reason}; document type not in catalogue",
            min_route_confidence=min_conf,
            score_breakdown=result.score_breakdown,
        )
    if not definition.enabled:
        return DocumentTypeClassification(
            result.code,
            min(result.confidence, min_conf - 0.01),
            f"{result.reason}; document type disabled",
            min_route_confidence=min_conf,
            score_breakdown=result.score_breakdown,
        )
    return DocumentTypeClassification(
        result.code,
        result.confidence,
        result.reason,
        min_route_confidence=min_conf,
        score_breakdown=result.score_breakdown,
    )


def _unclassified_result(
    unclassified: DocumentClassificationConfig | None,
    document_types: Sequence[DocumentTypeDefinition] | None,
) -> DocumentTypeClassification:
    settings = unclassified or DocumentClassificationConfig()
    code = settings.unclassified_document_type_code.strip().upper()
    if code and document_types:
        if get_document_type_definition(code, document_types=document_types) is None:
            code = ""
    confidence = settings.unclassified_min_confidence
    if not code:
        return DocumentTypeClassification(
            "",
            confidence,
            "No classifier matched in rule book catalogue",
            min_route_confidence=DOCUMENT_TYPE_ROUTE_CONFIDENCE_MIN,
        )
    min_conf = min_route_confidence_for_document_type(code, document_types)
    if confidence >= min_conf:
        confidence = round(max(0.0, min_conf - 0.01), 4)
    return _gate_classification(
        DocumentTypeClassification(
            code,
            confidence,
            "No classifier matched in rule book catalogue",
        ),
        document_types,
    )


def _score_configured_matches(
    *,
    document_types: Sequence[DocumentTypeDefinition],
    invoice: Invoice,
    parsed: InvoiceData,
    parse_confidence: ParseConfidence | None,
    heading_kind=None,
) -> DocumentTypeClassification | None:
    scored = _score_all_configured_matches(
        document_types=document_types,
        invoice=invoice,
        parsed=parsed,
        parse_confidence=parse_confidence,
        heading_kind=heading_kind,
    )
    best = pick_best_scored_definition(scored)
    if best is None:
        return None
    definition, breakdown, source = best
    return _classification_from_scored_match(definition, breakdown, source)


def _score_all_configured_matches(
    *,
    document_types: Sequence[DocumentTypeDefinition],
    invoice: Invoice,
    parsed: InvoiceData,
    parse_confidence: ParseConfidence | None,
    heading_kind=None,
) -> list[tuple[DocumentTypeDefinition, DocumentTypeScoreBreakdown, str]]:
    matches = list_heading_aware_document_type_matches(
        list(document_types),
        invoice=invoice,
        parsed=parsed,
        heading_kind=heading_kind,
    )
    if not matches:
        return []

    scored: list[tuple[DocumentTypeDefinition, DocumentTypeScoreBreakdown, str]] = []
    for definition, source in matches:
        breakdown = score_document_type_definition(
            definition,
            invoice=invoice,
            parsed=parsed,
            rule_strength=float(definition.classifier.confidence),
            parse_confidence=parse_confidence,
        )
        scored.append((definition, breakdown, source))
    return scored


def _classification_from_scored_match(
    definition: DocumentTypeDefinition,
    breakdown: DocumentTypeScoreBreakdown,
    source: str,
) -> DocumentTypeClassification:
    missing = breakdown.required_missing + breakdown.absent_violations
    reason = f"Rule book classifier matched ({source})"
    if missing:
        reason = f"{reason}; missing evidence: {', '.join(missing)}"
    if breakdown.signal_conflicts:
        reason = (
            f"{reason}; signal conflicts: {', '.join(breakdown.signal_conflicts)}"
        )
    return DocumentTypeClassification(
        definition.code,
        breakdown.confidence,
        reason,
        min_route_confidence=breakdown.min_route_confidence,
        score_breakdown=breakdown,
    )


def rank_document_type_candidates(
    *,
    document_types: Sequence[DocumentTypeDefinition],
    invoice: Invoice,
    parsed: InvoiceData,
    parse_confidence: ParseConfidence | None = None,
    limit: int = 5,
) -> list[DocumentTypeClassification]:
    """Return scored classifier matches ordered by confidence then specificity."""
    scored = _score_all_configured_matches(
        document_types=document_types,
        invoice=invoice,
        parsed=parsed,
        parse_confidence=parse_confidence,
    )
    if not scored:
        return []

    ordered = sorted(
        scored,
        key=lambda item: (
            item[1].confidence,
            -item[0].classifier.priority,
            item[1].field_completeness,
            -len(item[1].absent_violations),
            -len(item[1].required_missing),
            -len(item[1].signal_conflicts),
        ),
        reverse=True,
    )
    results: list[DocumentTypeClassification] = []
    for definition, breakdown, source in ordered[: max(1, limit)]:
        results.append(_classification_from_scored_match(definition, breakdown, source))
    return results


def classify_document_type(
    *,
    invoice: Invoice,
    parsed: InvoiceData,
    document_types: Sequence[DocumentTypeDefinition] | None = None,
    parse_confidence: ParseConfidence | None = None,
    unclassified: DocumentClassificationConfig | None = None,
    segment_heading_kind=None,
) -> DocumentTypeClassification:
    """Pick the best DT-xx match from Rule Book classifiers only."""
    if not document_types:
        return _unclassified_result(unclassified, document_types)

    heading_kind = resolve_segment_heading_kind(
        document_text=parsed.document_text,
        segment_heading_kind=segment_heading_kind,
    )

    configured = _score_configured_matches(
        document_types=document_types,
        invoice=invoice,
        parsed=parsed,
        parse_confidence=parse_confidence,
        heading_kind=heading_kind,
    )
    if configured is not None:
        return _gate_classification(configured, document_types)

    return _unclassified_result(unclassified, document_types)


def score_classifier_policy_matches(
    *,
    document_types: Sequence[DocumentTypeDefinition],
    invoice: Invoice,
    parsed: InvoiceData,
    parse_confidence: ParseConfidence | None = None,
    heading_kind=None,
):
    """Map classifier tree matches to policy scores for compare step."""
    from app.schemas.classification_decision import PolicyDtScore, PolicyScoreResult

    scored = _score_all_configured_matches(
        document_types=document_types,
        invoice=invoice,
        parsed=parsed,
        parse_confidence=parse_confidence,
        heading_kind=heading_kind,
    )
    if not scored:
        return None

    policy_scores: list[PolicyDtScore] = []
    for definition, breakdown, _source in scored:
        policy_scores.append(
            PolicyDtScore(
                code=definition.code.strip().upper(),
                confidence=breakdown.confidence,
                required_present=list(breakdown.required_present),
                required_missing=list(breakdown.required_missing),
                absent_violations=list(breakdown.absent_violations),
            )
        )
    ordered = sorted(policy_scores, key=lambda row: row.confidence, reverse=True)
    winner = ordered[0]
    return PolicyScoreResult(
        winner_dt=winner.code,
        winner_confidence=winner.confidence,
        scores=ordered,
    )


def apply_document_type_classification(
    invoice: Invoice,
    result: DocumentTypeClassification,
) -> None:
    code = (result.code or "").strip()
    invoice.document_type_code = code or None
    invoice.document_type_confidence = round(result.confidence, 4)


def classification_audit_detail(
    result: DocumentTypeClassification,
    *,
    document_types: Sequence[DocumentTypeDefinition] | None = None,
    tenant_id: int | None = None,
) -> dict[str, object]:
    definition = get_document_type_definition(
        result.code,
        document_types=document_types,
        tenant_id=tenant_id,
    )
    detail: dict[str, object] = {
        "document_type_code": result.code,
        "document_type_confidence": result.confidence,
        "document_type_title": definition.title if definition else None,
        "document_type_klass": definition.klass if definition else None,
        "reason": result.reason,
        "needs_review": result.needs_review,
        "min_route_confidence": result.min_route_confidence,
    }
    if result.score_breakdown is not None:
        detail["score_breakdown"] = {
            "rule_strength": result.score_breakdown.rule_strength,
            "field_completeness": result.score_breakdown.field_completeness,
            "parse_score": result.score_breakdown.parse_score,
            "heading_alignment": result.score_breakdown.heading_alignment,
            "confidence": result.score_breakdown.confidence,
            "required_present": result.score_breakdown.required_present,
            "required_missing": result.score_breakdown.required_missing,
            "absent_ok": result.score_breakdown.absent_ok,
            "absent_violations": result.score_breakdown.absent_violations,
            "signal_conflicts": result.score_breakdown.signal_conflicts,
        }
        if result.score_breakdown.signal_conflicts:
            detail["signal_conflicts"] = result.score_breakdown.signal_conflicts
    return detail
