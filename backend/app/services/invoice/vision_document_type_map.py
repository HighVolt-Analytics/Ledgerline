"""Map vision header labels to a tenant Rule Book DT-xx.

1) Deterministic heading-kind scoring (same scorer as PDF segment classify).
2) When an invoice row is available: tenant configured classifiers
   (recognition signals, or playbook-recommended identity signals).
3) Optional text-LLM catalogue fallback — may pick ONLY a catalogue DT-xx
   code, or leave empty.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.segment_heading_classification import (
    heading_conflicts_with_definition,
    resolve_segment_heading_with_source,
    score_document_type_for_heading,
)
from app.services.invoice.vision_header_extract import derive_canonical_document_type
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MATCH_THRESHOLD = 0.82
_AMBIGUITY_MARGIN = 0.05
_METHOD_RULES = "heading_kind_score"
_METHOD_CLASSIFIER = "config_classifier"
_METHOD_LLM = "llm_catalogue_fallback"
_LLM_FALLBACK_REASONS = frozenset({"no_kind", "below_threshold", "ambiguous"})
_LLM_MIN_CONFIDENCE = 0.55
_PROMPT_KEY = "vision.dt_map_fallback.system"


@dataclass(frozen=True)
class VisionDocumentTypeMapResult:
    code: str | None
    confidence: float
    heading_kind: str | None
    reason: str
    # matched | below_threshold | ambiguous | no_kind | human_locked | empty_catalogue
    # | classifier_matched | classifier_no_match
    # | llm_matched | llm_empty | llm_rejected | llm_error | llm_unavailable
    method: str = _METHOD_RULES
    runner_up_code: str | None = None
    runner_up_score: float | None = None
    rule_reason: str | None = None  # prior rule outcome when a fallback ran
    llm_reasoning: str | None = None


def map_vision_label_to_document_type(
    *,
    document_heading: str,
    canonical_document_type: str,
    document_types: Sequence[DocumentTypeDefinition],
    human_locked_dt: str = "",
) -> VisionDocumentTypeMapResult:
    """Deterministic resolve vision heading/canonical label → Rule Book DT code."""
    locked = (human_locked_dt or "").strip().upper()
    if locked:
        return VisionDocumentTypeMapResult(
            code=locked,
            confidence=1.0,
            heading_kind=None,
            reason="human_locked",
            method=_METHOD_RULES,
        )

    enabled = [dt for dt in document_types if getattr(dt, "enabled", True)]
    if not enabled:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=None,
            reason="empty_catalogue",
            method=_METHOD_RULES,
        )

    canonical = derive_canonical_document_type(
        document_heading=document_heading or "",
        canonical_document_type=canonical_document_type or "",
    )
    blob = "\n".join(
        part.strip()
        for part in (document_heading or "", canonical)
        if (part or "").strip()
    )
    if not blob.strip():
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=None,
            reason="no_kind",
            method=_METHOD_RULES,
        )

    inferred = resolve_segment_heading_with_source(document_text=blob)
    heading_kind = inferred.kind if inferred else None
    if heading_kind is None:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=None,
            reason="no_kind",
            method=_METHOD_RULES,
        )

    scored: list[tuple[DocumentTypeDefinition, float]] = []
    for definition in enabled:
        if heading_conflicts_with_definition(heading_kind, definition):
            continue
        score = score_document_type_for_heading(definition, heading_kind)
        if score >= _MATCH_THRESHOLD:
            scored.append((definition, score))

    if not scored:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=str(heading_kind),
            reason="below_threshold",
            method=_METHOD_RULES,
        )

    scored.sort(
        key=lambda item: (item[1], -int(getattr(item[0].classifier, "priority", 100) or 100)),
        reverse=True,
    )
    best_def, best_score = scored[0]
    runner_up_code: str | None = None
    runner_up_score: float | None = None
    if len(scored) > 1:
        runner_up_code = (scored[1][0].code or "").strip().upper() or None
        runner_up_score = scored[1][1]
        if (best_score - runner_up_score) < _AMBIGUITY_MARGIN:
            return VisionDocumentTypeMapResult(
                code=None,
                confidence=0.0,
                heading_kind=str(heading_kind),
                reason="ambiguous",
                method=_METHOD_RULES,
                runner_up_code=runner_up_code,
                runner_up_score=runner_up_score,
            )

    code = (best_def.code or "").strip().upper() or None
    if not code:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=str(heading_kind),
            reason="below_threshold",
            method=_METHOD_RULES,
        )

    return VisionDocumentTypeMapResult(
        code=code,
        confidence=round(float(best_score), 4),
        heading_kind=str(heading_kind),
        reason="matched",
        method=_METHOD_RULES,
        runner_up_code=runner_up_code,
        runner_up_score=runner_up_score,
    )


_INVOICE_LIKE_HEADING_KINDS = frozenset(
    {"invoice", "tax_invoice", "commercial_invoice"}
)


def map_vision_via_configured_classifiers(
    *,
    invoice: Any,
    document_types: Sequence[DocumentTypeDefinition],
    heading_kind: str | None,
    rule_fail_reason: str,
) -> VisionDocumentTypeMapResult:
    """Deterministic tenant classifier match over persisted vision fields.

    Uses Rule Book recognition signals (and playbook-recommended identity
    signals when a DT only has playbookProfile). Field checks like
    ``has_po_reference`` separate PO-goods from non-PO invoice DTs without
    scraping prompt English.
    """
    from app.services.classification.segment_heading_classification import (
        list_heading_aware_document_type_matches,
        parse_segment_heading_kind,
    )
    from app.services.invoice.invoice_data import invoice_data_from_invoice

    parsed = invoice_data_from_invoice(invoice)
    matches = list_heading_aware_document_type_matches(
        list(document_types),
        invoice=invoice,
        parsed=parsed,
        heading_kind=parse_segment_heading_kind(heading_kind),
    )
    if not matches:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=heading_kind,
            reason="classifier_no_match",
            method=_METHOD_CLASSIFIER,
            rule_reason=rule_fail_reason,
        )

    definition, _source = matches[0]
    code = (definition.code or "").strip().upper() or None
    if not code:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=heading_kind,
            reason="classifier_no_match",
            method=_METHOD_CLASSIFIER,
            rule_reason=rule_fail_reason,
        )

    try:
        confidence = float(getattr(definition.classifier, "confidence", 0.85) or 0.85)
    except (TypeError, ValueError):
        confidence = 0.85
    runner_up = matches[1][0] if len(matches) > 1 else None
    return VisionDocumentTypeMapResult(
        code=code,
        confidence=round(min(max(confidence, 0.0), 1.0), 4),
        heading_kind=heading_kind,
        reason="classifier_matched",
        method=_METHOD_CLASSIFIER,
        rule_reason=rule_fail_reason,
        runner_up_code=(runner_up.code or "").strip().upper() or None
        if runner_up is not None
        else None,
    )


def _allowed_catalogue_codes(document_types: Sequence[DocumentTypeDefinition]) -> set[str]:
    return {
        (dt.code or "").strip().upper()
        for dt in document_types
        if getattr(dt, "enabled", True) and (dt.code or "").strip()
    }


def _parse_llm_confidence(raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if value > 1.0 and value <= 100.0:
        value = value / 100.0
    return max(0.0, min(1.0, value))


async def _llm_pick_catalogue_dt(
    *,
    document_heading: str,
    canonical_document_type: str,
    heading_kind: str | None,
    rule_fail_reason: str,
    document_types: Sequence[DocumentTypeDefinition],
) -> VisionDocumentTypeMapResult:
    from app.config import get_settings
    from app.services.extraction.azure_openai_client import chat_json_async
    from app.services.extraction.llm_catalogue_rows import build_llm_catalogue_rows
    from app.services.prompt_registry.service import resolve_system_prompt_text

    enabled = [dt for dt in document_types if getattr(dt, "enabled", True)]
    allowed = _allowed_catalogue_codes(enabled)
    if not allowed:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=heading_kind,
            reason="empty_catalogue",
            method=_METHOD_LLM,
            rule_reason=rule_fail_reason,
        )

    system = resolve_system_prompt_text(_PROMPT_KEY)
    user: dict[str, Any] = {
        "task": "map_vision_label_to_catalogue_dt",
        "document_heading": (document_heading or "").strip(),
        "canonical_document_type": (canonical_document_type or "").strip(),
        "heading_kind": heading_kind or "",
        "rule_fail_reason": rule_fail_reason,
        "catalogue": build_llm_catalogue_rows(enabled),
        "output_keys": ["suggested_dt", "confidence", "reasoning"],
    }

    settings = get_settings()
    try:
        raw = await chat_json_async(
            system=system,
            user=user,
            timeout_seconds=settings.runtime_llm_timeout_seconds,
            require_runtime=True,
        )
    except Exception as exc:
        logger.warning("vision_dt_map_llm_error", error=str(exc), reason=rule_fail_reason)
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=heading_kind,
            reason="llm_error",
            method=_METHOD_LLM,
            rule_reason=rule_fail_reason,
            llm_reasoning=str(exc)[:300],
        )

    if not isinstance(raw, dict):
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=heading_kind,
            reason="llm_unavailable",
            method=_METHOD_LLM,
            rule_reason=rule_fail_reason,
        )

    suggested = str(raw.get("suggested_dt") or "").strip().upper()
    confidence = _parse_llm_confidence(raw.get("confidence"))
    reasoning = str(raw.get("reasoning") or "").strip()[:500] or None

    if not suggested:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=confidence,
            heading_kind=heading_kind,
            reason="llm_empty",
            method=_METHOD_LLM,
            rule_reason=rule_fail_reason,
            llm_reasoning=reasoning,
        )

    if suggested not in allowed:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=0.0,
            heading_kind=heading_kind,
            reason="llm_rejected",
            method=_METHOD_LLM,
            rule_reason=rule_fail_reason,
            llm_reasoning=f"invalid_code:{suggested}" + (f"; {reasoning}" if reasoning else ""),
        )

    if confidence < _LLM_MIN_CONFIDENCE:
        return VisionDocumentTypeMapResult(
            code=None,
            confidence=confidence,
            heading_kind=heading_kind,
            reason="llm_rejected",
            method=_METHOD_LLM,
            rule_reason=rule_fail_reason,
            llm_reasoning=f"low_confidence:{confidence}" + (f"; {reasoning}" if reasoning else ""),
        )

    return VisionDocumentTypeMapResult(
        code=suggested,
        confidence=round(confidence, 4),
        heading_kind=heading_kind,
        reason="llm_matched",
        method=_METHOD_LLM,
        rule_reason=rule_fail_reason,
        llm_reasoning=reasoning,
    )


async def map_vision_label_to_document_type_with_llm_fallback(
    *,
    document_heading: str,
    canonical_document_type: str,
    document_types: Sequence[DocumentTypeDefinition],
    human_locked_dt: str = "",
    invoice: Any | None = None,
) -> VisionDocumentTypeMapResult:
    """Rules first; tenant classifiers next; text LLM catalogue pick last.

    For invoice-like headings, configured classifiers (recognition signals /
    playbook-recommended identity) refine the pick whenever an invoice row is
    available — so ``has_po_reference`` can beat a generic heading match.
    """
    rule = map_vision_label_to_document_type(
        document_heading=document_heading,
        canonical_document_type=canonical_document_type,
        document_types=document_types,
        human_locked_dt=human_locked_dt,
    )
    if rule.reason == "human_locked":
        return rule

    invoice_like = (rule.heading_kind or "") in _INVOICE_LIKE_HEADING_KINDS
    if invoice is not None and (rule.reason in _LLM_FALLBACK_REASONS or invoice_like):
        classifier = map_vision_via_configured_classifiers(
            invoice=invoice,
            document_types=document_types,
            heading_kind=rule.heading_kind,
            rule_fail_reason=rule.reason
            if rule.reason in _LLM_FALLBACK_REASONS
            else "field_refine",
        )
        if classifier.reason == "classifier_matched" and classifier.code:
            return replace(
                classifier,
                runner_up_score=classifier.runner_up_score or rule.runner_up_score,
            )

    if rule.reason not in _LLM_FALLBACK_REASONS:
        return rule

    canonical = derive_canonical_document_type(
        document_heading=document_heading or "",
        canonical_document_type=canonical_document_type or "",
    )
    llm = await _llm_pick_catalogue_dt(
        document_heading=document_heading or "",
        canonical_document_type=canonical,
        heading_kind=rule.heading_kind,
        rule_fail_reason=rule.reason,
        document_types=document_types,
    )
    if llm.reason == "llm_matched" and llm.code:
        return replace(
            llm,
            runner_up_code=rule.runner_up_code,
            runner_up_score=rule.runner_up_score,
        )
    if llm.reason in {"llm_empty", "llm_rejected", "llm_error", "llm_unavailable"}:
        return replace(
            llm,
            runner_up_code=rule.runner_up_code,
            runner_up_score=rule.runner_up_score,
        )
    return rule
