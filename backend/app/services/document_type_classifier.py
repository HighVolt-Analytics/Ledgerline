"""Classify parsed invoices to DT-xx codes from Rule Book config only."""

from __future__ import annotations

from dataclasses import dataclass

from collections.abc import Sequence

from app.models.invoice import Invoice
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.rule_book_config import DocumentClassificationConfig
from app.services.document_type_catalog import (
    DOCUMENT_TYPE_ROUTE_CONFIDENCE_MIN,
    get_document_type_definition,
    min_route_confidence_for_document_type,
    resolve_document_type_for_purchase_kind,
)
from app.services.document_type_rule_engine import list_configured_document_type_matches
from app.services.document_type_scoring_service import (
    DocumentTypeScoreBreakdown,
    pick_best_scored_definition,
    score_document_type_definition,
)
from app.services.invoice_data import InvoiceData, ParseConfidence

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
) -> DocumentTypeClassification | None:
    matches = list_configured_document_type_matches(
        list(document_types),
        invoice=invoice,
        parsed=parsed,
    )
    if not matches:
        return None

    scored: list[tuple[DocumentTypeDefinition, DocumentTypeScoreBreakdown, str]] = []
    for definition, source in matches:
        breakdown = score_document_type_definition(
            definition,
            invoice=invoice,
            parsed=parsed,
            rule_strength=CONFIG_RULE_STRENGTH,
            parse_confidence=parse_confidence,
        )
        scored.append((definition, breakdown, source))

    best = pick_best_scored_definition(scored)
    if best is None:
        return None
    definition, breakdown, source = best
    missing = breakdown.required_missing + breakdown.absent_violations
    reason = f"Rule book classifier matched ({source})"
    if missing:
        reason = f"{reason}; missing evidence: {', '.join(missing)}"
    return DocumentTypeClassification(
        definition.code,
        breakdown.confidence,
        reason,
        min_route_confidence=breakdown.min_route_confidence,
        score_breakdown=breakdown,
    )


PURCHASE_KIND_FALLBACK_STRENGTH = 0.78


def _classify_from_purchase_kind(
    *,
    invoice: Invoice,
    parsed: InvoiceData,
    document_types: Sequence[DocumentTypeDefinition],
    parse_confidence: ParseConfidence | None,
) -> DocumentTypeClassification | None:
    from app.services.purchase_document_service import infer_purchase_document_type

    kind = infer_purchase_document_type(invoice)
    if not kind:
        return None
    definition = resolve_document_type_for_purchase_kind(kind, document_types)
    if definition is None:
        return None
    breakdown = score_document_type_definition(
        definition,
        invoice=invoice,
        parsed=parsed,
        rule_strength=PURCHASE_KIND_FALLBACK_STRENGTH,
        parse_confidence=parse_confidence,
    )
    return DocumentTypeClassification(
        definition.code,
        breakdown.confidence,
        f"Purchase document role inferred as {kind}",
        min_route_confidence=breakdown.min_route_confidence,
        score_breakdown=breakdown,
    )


def classify_document_type(
    *,
    invoice: Invoice,
    parsed: InvoiceData,
    document_types: Sequence[DocumentTypeDefinition] | None = None,
    parse_confidence: ParseConfidence | None = None,
    unclassified: DocumentClassificationConfig | None = None,
) -> DocumentTypeClassification:
    """Pick the best DT-xx match from Rule Book classifiers only."""
    if not document_types:
        return _unclassified_result(unclassified, document_types)

    configured = _score_configured_matches(
        document_types=document_types,
        invoice=invoice,
        parsed=parsed,
        parse_confidence=parse_confidence,
    )
    if configured is not None:
        return _gate_classification(configured, document_types)
    purchase_fallback = _classify_from_purchase_kind(
        invoice=invoice,
        parsed=parsed,
        document_types=document_types,
        parse_confidence=parse_confidence,
    )
    if purchase_fallback is not None:
        return _gate_classification(purchase_fallback, document_types)
    return _unclassified_result(unclassified, document_types)


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
    org_id: int | None = None,
) -> dict[str, object]:
    definition = get_document_type_definition(
        result.code,
        document_types=document_types,
        org_id=org_id,
    )
    detail: dict[str, object] = {
        "document_type_code": result.code,
        "document_type_confidence": result.confidence,
        "document_type_title": definition.short_title if definition else None,
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
            "required_present": result.score_breakdown.required_present,
            "required_missing": result.score_breakdown.required_missing,
            "absent_ok": result.score_breakdown.absent_ok,
            "absent_violations": result.score_breakdown.absent_violations,
        }
    return detail
