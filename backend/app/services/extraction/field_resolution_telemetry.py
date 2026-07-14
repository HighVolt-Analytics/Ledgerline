"""Read-only DI vs LLM field-resolution telemetry (logging / reporting only)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Sequence

from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.extraction_field_values import (
    di_scalar_fields_populated,
    prebuilt_invoice_scalars_active,
)
from app.services.extraction.field_contracts import (
    FieldCandidate,
    FieldResolutionResult,
    FieldSource,
    normalize_field_source,
)
from app.services.invoice.invoice_data import InvoiceData

POSTING_CRITICAL_FIELDS: tuple[str, ...] = (
    "total",
    "subtotal",
    "gst",
    "line_items",
    "invoice_no",
    "vendor",
)

_DI_SOURCES = {FieldSource.SEMANTIC_DI.value, FieldSource.AZURE_DI.value, "semantic_di", "azure_di"}
_LLM_SOURCES = {FieldSource.LLM.value, "llm"}


def _serialize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return {"count": len(value), "sample": [_serialize_value(v) for v in value[:3]]}
    return str(value)


def _normalize_chosen_source(raw: str | None) -> str:
    token = str(raw or "").strip().lower()
    if token in _DI_SOURCES:
        return "azure_di"
    if token in _LLM_SOURCES:
        return "llm"
    if not token:
        return "missing"
    return "fallback"


def _candidate_for_sources(
    candidates: Sequence[FieldCandidate],
    sources: set[str],
) -> FieldCandidate | None:
    for candidate in candidates:
        normalized = normalize_field_source(candidate.source).value
        if normalized in sources or str(candidate.source).strip().lower() in sources:
            return candidate
    return None


def _values_agree(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    return str(_serialize_value(left)) == str(_serialize_value(right))


def build_posting_critical_telemetry(
    results: Sequence[FieldResolutionResult],
    candidates_by_key: dict[str, list[FieldCandidate]],
    *,
    ocr: OcrArtifact | None = None,
    document_ai_provider: str | None = None,
) -> dict[str, Any]:
    """Build per-field DI vs LLM telemetry rows from contract merge resolution."""
    by_key = {r.key: r for r in results}
    fields: dict[str, dict[str, Any]] = {}
    for field_name in POSTING_CRITICAL_FIELDS:
        result = by_key.get(field_name)
        candidates = candidates_by_key.get(field_name, [])
        di_candidate = _candidate_for_sources(candidates, _DI_SOURCES)
        llm_candidate = _candidate_for_sources(candidates, _LLM_SOURCES)
        di_value = di_candidate.value if di_candidate is not None else None
        llm_value = llm_candidate.value if llm_candidate is not None else None
        di_confidence = di_candidate.confidence if di_candidate is not None else None
        chosen_source = _normalize_chosen_source(result.chosen_source if result else None)
        chosen_value = result.value if result is not None else None
        agreed = _values_agree(di_value, llm_value)
        fields[field_name] = {
            "field_name": field_name,
            "chosen_source": chosen_source,
            "di_value": _serialize_value(di_value),
            "llm_value": _serialize_value(llm_value),
            "chosen_value": _serialize_value(chosen_value),
            "di_confidence": di_confidence,
            "agreed": agreed,
            "resolution_status": (
                result.resolution_status.value if result is not None else "missing"
            ),
        }
    return _wrap_detail(fields, ocr=ocr, document_ai_provider=document_ai_provider)


def build_legacy_merge_telemetry(
    *,
    field_keys: Sequence[str],
    llm_parsed: InvoiceData | None,
    di_parsed: InvoiceData | None,
    merged: InvoiceData,
    ocr: OcrArtifact | None = None,
    document_ai_provider: str | None = None,
) -> dict[str, Any]:
    """Build telemetry for legacy layered merge using source snapshots."""
    fields: dict[str, dict[str, Any]] = {}
    for field_name in POSTING_CRITICAL_FIELDS:
        if field_name not in field_keys and field_name != "line_items":
            continue
        di_value = getattr(di_parsed, field_name, None) if di_parsed is not None else None
        llm_value = getattr(llm_parsed, field_name, None) if llm_parsed is not None else None
        chosen_value = getattr(merged, field_name, None)
        sources: dict[str, Any] = {}
        if di_value is not None and str(di_value).strip():
            sources["azure_di"] = _serialize_value(di_value)
        if llm_value is not None and str(llm_value).strip():
            sources["llm"] = _serialize_value(llm_value)
        chosen_source = "missing"
        serialized_chosen = _serialize_value(chosen_value)
        for source_name, source_value in sources.items():
            if str(source_value) == str(serialized_chosen):
                chosen_source = source_name
                break
        if chosen_source == "missing" and serialized_chosen is not None:
            chosen_source = "fallback"
        fields[field_name] = {
            "field_name": field_name,
            "chosen_source": chosen_source,
            "di_value": _serialize_value(di_value),
            "llm_value": _serialize_value(llm_value),
            "chosen_value": serialized_chosen,
            "di_confidence": _di_field_confidence(ocr, field_name),
            "agreed": _values_agree(di_value, llm_value),
            "resolution_status": "legacy_merge",
        }
    return _wrap_detail(fields, ocr=ocr, document_ai_provider=document_ai_provider)


def attach_field_resolution_telemetry(
    parsed: InvoiceData,
    detail: dict[str, Any],
) -> InvoiceData:
    """Attach telemetry blob to parsed.raw_fields without changing scalar fields."""
    if not detail.get("fields"):
        return parsed
    from dataclasses import replace

    raw = dict(parsed.raw_fields or {})
    raw["_field_resolution_telemetry"] = detail
    return replace(parsed, raw_fields=raw)


def detail_from_parsed_telemetry(parsed: InvoiceData) -> dict[str, Any] | None:
    raw = parsed.raw_fields or {}
    detail = raw.get("_field_resolution_telemetry")
    return detail if isinstance(detail, dict) else None


def _di_field_confidence(ocr: OcrArtifact | None, field_name: str) -> float | None:
    if ocr is None:
        return None
    payload = ocr.payload_json or {}
    conf_map = payload.get("field_confidence")
    if not isinstance(conf_map, dict):
        return None
    raw = conf_map.get(field_name)
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _di_availability(ocr: OcrArtifact | None) -> dict[str, Any]:
    payload = dict(ocr.payload_json or {}) if ocr is not None else {}
    invoice_fields = payload.get("invoice_fields")
    di_line_items = payload.get("di_line_items")
    invoice_fields_present = isinstance(invoice_fields, dict) and bool(invoice_fields)
    di_line_items_count = len(di_line_items) if isinstance(di_line_items, list) else 0
    scalars_active = prebuilt_invoice_scalars_active(payload)
    scalars_populated = sorted(di_scalar_fields_populated(payload)) if scalars_active else []
    di_available = bool(
        invoice_fields_present
        or di_line_items_count > 0
        or payload.get("extraction_route")
        or payload.get("finance_document")
    )
    return {
        "di_available": di_available,
        "invoice_fields_present": invoice_fields_present,
        "di_line_items_count": di_line_items_count,
        "prebuilt_invoice_scalars_active": scalars_active,
        "di_scalars_populated": scalars_populated,
        "extraction_route": payload.get("extraction_route"),
    }


def _wrap_detail(
    fields: dict[str, dict[str, Any]],
    *,
    ocr: OcrArtifact | None,
    document_ai_provider: str | None,
) -> dict[str, Any]:
    from app.config import get_settings

    settings = get_settings()
    return {
        "document_ai_provider": document_ai_provider,
        "di_trust_min_confidence": settings.di_field_trust_min_confidence,
        "merge_mode": (
            "field_contract" if settings.use_field_contract_merge else "legacy"
        ),
        "di_availability": _di_availability(ocr),
        "fields": fields,
    }
