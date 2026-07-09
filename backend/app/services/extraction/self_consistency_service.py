"""Self-consistency checks for posting-critical extraction fields."""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable

from app.registry.adapter import get_registry_adapter
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.services.classification.document_type_field_keys import posting_critical_field_keys
from app.services.extraction.citation_grounding_service import (
    _field_value_from_llm,
    verify_and_apply_citations,
)
from app.services.shared.flexible_date import parse_flexible_date

logger = logging.getLogger(__name__)

_SELF_CONSISTENCY_DISAGREEMENT_CAP = 0.4
_MAX_SELF_CONSISTENCY_FIELDS = 15


def _normalize_value(field_key: str, value: Any) -> str:
    token = field_key.strip().lower()
    if value is None:
        return ""
    if token in {"invoice_date", "due_date"}:
        if hasattr(value, "isoformat"):
            return value.isoformat()
        parsed = parse_flexible_date(str(value))
        return parsed.isoformat() if parsed else str(value).strip()
    if token in {"subtotal", "gst", "gst_rate", "total"}:
        try:
            return format(Decimal(str(value)).normalize(), "f")
        except (InvalidOperation, ValueError):
            return str(value).strip()
    return " ".join(str(value).strip().upper().split())


def posting_critical_keys_for_dt(dt_definition: DocumentTypeDefinition | None) -> list[str]:
    required = list(dt_definition.required_fields or []) if dt_definition else []
    critical = posting_critical_field_keys(required or None)
    if not critical and dt_definition is not None:
        registry_critical = get_registry_adapter().posting_critical_keys()
        extraction = [str(k).strip().lower() for k in (dt_definition.extraction_fields or [])]
        critical = [key for key in extraction if key in registry_critical]
    return critical[:_MAX_SELF_CONSISTENCY_FIELDS]


def compare_self_consistency(
    base: LlmDocumentResult,
    retries: list[LlmDocumentResult],
    field_keys: list[str],
) -> dict[str, dict[str, Any]]:
    outcomes: dict[str, dict[str, Any]] = {}
    for key in field_keys:
        values = [_normalize_value(key, _field_value_from_llm(base, key))]
        for retry in retries:
            values.append(_normalize_value(key, _field_value_from_llm(retry, key)))
        non_empty = [value for value in values if value]
        if not non_empty:
            outcomes[key] = {"agreed": True, "values": values, "final": ""}
            continue
        counts: dict[str, int] = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1
        winner = max(counts, key=counts.get)
        agreed = counts[winner] >= 2 and all(value in {"", winner} for value in values)
        outcomes[key] = {
            "agreed": agreed,
            "values": values,
            "final": winner if agreed else values[0],
        }
    return outcomes


def apply_self_consistency_outcomes(
    result: LlmDocumentResult,
    outcomes: dict[str, dict[str, Any]],
) -> LlmDocumentResult:
    confidence = dict(result.field_confidence)
    for key, outcome in outcomes.items():
        if outcome.get("agreed"):
            continue
        confidence[key] = min(confidence.get(key, 1.0), _SELF_CONSISTENCY_DISAGREEMENT_CAP)
    return result.model_copy(update={"field_confidence": confidence})


async def run_self_consistency(
    *,
    base_result: LlmDocumentResult,
    ocr: OcrArtifact,
    dt_definition: DocumentTypeDefinition | None,
    extract_fn: Callable[..., Awaitable[LlmDocumentResult | None]],
    extract_kwargs: dict[str, Any],
    use_citation_grounding: bool,
) -> tuple[LlmDocumentResult, dict[str, dict[str, Any]]]:
    if not use_citation_grounding:
        logger.warning("self_consistency_skipped: citation grounding disabled")
        return base_result, {}

    field_keys = posting_critical_keys_for_dt(dt_definition)
    if not field_keys:
        return base_result, {}

    retries: list[LlmDocumentResult] = []
    kwargs = dict(extract_kwargs)
    for _ in range(2):
        retry = await extract_fn(**kwargs)
        if retry is None:
            continue
        if use_citation_grounding:
            retry, _ = verify_and_apply_citations(retry, ocr, field_keys=field_keys)
        retries.append(retry)

    outcomes = compare_self_consistency(base_result, retries, field_keys)
    updated = apply_self_consistency_outcomes(base_result, outcomes)
    return updated, outcomes
