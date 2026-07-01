"""Field-based Rule Book policy scoring for LLM-first classification."""

from __future__ import annotations

from collections.abc import Sequence

from app.models.invoice import Invoice
from app.schemas.classification_decision import PolicyDtScore, PolicyScoreResult
from app.schemas.document_type import DocumentTypeDefinition
from app.services.document_type_field_checks import field_is_absent, field_is_present
from app.services.document_type_playbook_service import effective_extraction_fields
from app.services.document_type_rule_engine import build_document_classifier_context
from app.services.invoice_data import InvoiceData, ParseConfidence
from app.services.rule_engine import classifier_has_actionable_conditions


def _definition_has_classifier(defn: DocumentTypeDefinition) -> bool:
    return bool(
        defn.enabled
        and defn.classifier.enabled
        and classifier_has_actionable_conditions(defn.classifier.root)
    )


def _catalogue_has_enabled_classifiers(
    document_types: Sequence[DocumentTypeDefinition],
) -> bool:
    return any(_definition_has_classifier(defn) for defn in document_types)


def policy_score_from_classifiers(
    *,
    invoice: Invoice,
    parsed: InvoiceData,
    document_types: Sequence[DocumentTypeDefinition],
    parse_confidence: ParseConfidence | None = None,
    heading_kind=None,
) -> PolicyScoreResult | None:
    """Deterministic policy winner from Rule Book classifier trees."""
    from app.services.document_type_classifier import score_classifier_policy_matches

    return score_classifier_policy_matches(
        invoice=invoice,
        parsed=parsed,
        document_types=document_types,
        parse_confidence=parse_confidence,
        heading_kind=heading_kind,
    )


def _score_definition(
    definition: DocumentTypeDefinition,
    *,
    invoice: Invoice,
    parsed: InvoiceData,
) -> PolicyDtScore:
    ctx = build_document_classifier_context(invoice=invoice, parsed=parsed)
    required = list(definition.required_fields or [])
    absent = list(definition.absent_fields or [])
    extraction = effective_extraction_fields(definition)

    required_present: list[str] = []
    required_missing: list[str] = []
    for key in required:
        if field_is_present(key, invoice=invoice, parsed=parsed, ctx=ctx):
            required_present.append(key)
        else:
            required_missing.append(key)

    absent_violations: list[str] = []
    for key in absent:
        if not field_is_absent(key, invoice=invoice, parsed=parsed, ctx=ctx):
            absent_violations.append(key)

    extraction_present = 0
    for key in extraction:
        if field_is_present(key, invoice=invoice, parsed=parsed, ctx=ctx):
            extraction_present += 1

    req_total = len(required) or 1
    abs_total = len(absent) or 1
    ext_total = len(extraction) or 1

    req_score = len(required_present) / req_total
    abs_score = (len(absent) - len(absent_violations)) / abs_total if absent else 1.0
    ext_score = extraction_present / ext_total if extraction else 1.0

    confidence = round(req_score * 0.55 + abs_score * 0.25 + ext_score * 0.20, 4)
    if absent_violations:
        confidence = round(min(confidence, definition.min_route_confidence - 0.01), 4)

    return PolicyDtScore(
        code=definition.code.strip().upper(),
        confidence=confidence,
        required_present=required_present,
        required_missing=required_missing,
        absent_violations=absent_violations,
    )


def score_all_enabled_dts(
    *,
    invoice: Invoice,
    parsed: InvoiceData,
    document_types: Sequence[DocumentTypeDefinition],
    parse_confidence: ParseConfidence | None = None,
    heading_kind=None,
) -> PolicyScoreResult:
    if _catalogue_has_enabled_classifiers(document_types):
        classifier_policy = policy_score_from_classifiers(
            invoice=invoice,
            parsed=parsed,
            document_types=document_types,
            parse_confidence=parse_confidence,
            heading_kind=heading_kind,
        )
        if classifier_policy is not None:
            return classifier_policy
        return PolicyScoreResult(winner_dt="", winner_confidence=0.0, scores=[])

    scores: list[PolicyDtScore] = []
    for defn in document_types:
        if not defn.enabled:
            continue
        scores.append(
            _score_definition(defn, invoice=invoice, parsed=parsed)
        )

    if not scores:
        return PolicyScoreResult(winner_dt="", winner_confidence=0.0, scores=[])

    ordered = sorted(
        scores,
        key=lambda row: (
            row.confidence,
            -len(row.required_missing),
            -len(row.absent_violations),
        ),
        reverse=True,
    )
    winner = ordered[0]
    return PolicyScoreResult(
        winner_dt=winner.code,
        winner_confidence=winner.confidence,
        scores=ordered,
    )
