"""Dedicated Currency Detection Agent (llm.currency.system) for invoice currency."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, TYPE_CHECKING

from app.config import get_settings
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.azure_openai_client import chat_json_async
from app.services.extraction.extraction_field_values import build_smart_ocr_excerpt
from app.services.invoice.invoice_data import InvoiceData
from app.services.prompt_registry import resolve_system_prompt_text
from app.services.shared.iso4217_catalog import is_iso4217_currency
from app.services.tenant.tenant_org_context import OrgContext
from app.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.schemas.document_type import DocumentTypeDefinition

logger = get_logger(__name__)

_MIN_APPLY_CONFIDENCE = 0.90
_UNCERTAIN_TOKENS = frozenset({"", "UNCERTAIN", "N/A", "NA", "NONE", "UNKNOWN"})


def currency_detection_needed(parsed: InvoiceData) -> bool:
    """True when currency ISO is still empty (ambiguous symbol-only counts as empty)."""
    return not (parsed.currency or "").strip()


def _document_type_hint(dt_definition: DocumentTypeDefinition | None) -> str | None:
    if dt_definition is None:
        return None
    for attr in ("short_title", "title", "code", "name"):
        value = getattr(dt_definition, attr, None)
        if value and str(value).strip():
            return str(value).strip()
    return None


def build_currency_detect_user_payload(
    *,
    ocr: OcrArtifact,
    org: OrgContext,
    dt_definition: DocumentTypeDefinition | None = None,
) -> str:
    payload: dict[str, Any] = {
        "document_text": build_smart_ocr_excerpt(ocr.text),
        "document_type_hint": _document_type_hint(dt_definition),
        "tenant_country_hint": (org.country or "").strip().upper() or None,
        "ocr_text_length": ocr.text_length,
    }
    return json.dumps(payload, default=str)


def parse_currency_detection_result(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize agent JSON into an apply-ready summary."""
    empty: dict[str, Any] = {
        "iso_code": "",
        "confidence": 0.0,
        "human_review_required": True,
        "review_reason": "Currency detection returned no usable payload",
        "symbol_seen": "",
        "critical_flags": [],
        "multi_currency_document": False,
        "raw": raw or {},
        "applied": False,
    }
    if not isinstance(raw, dict):
        return empty

    doc = raw.get("document_currency")
    if not isinstance(doc, dict):
        doc = {}
    iso_raw = str(doc.get("iso_code") or "").strip().upper()
    try:
        confidence = float(doc.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    human_review = bool(raw.get("human_review_required"))
    review_reason = raw.get("review_reason")
    if review_reason is not None:
        review_reason = str(review_reason).strip() or None
    flags = [
        str(f).strip()
        for f in (raw.get("critical_flags") or [])
        if str(f or "").strip()
    ]
    symbol_seen = str(doc.get("symbol_seen") or "").strip()

    if iso_raw in _UNCERTAIN_TOKENS:
        return {
            "iso_code": "",
            "confidence": confidence,
            "human_review_required": True if iso_raw != "N/A" else False,
            "review_reason": review_reason
            or ("No monetary amounts / not a finance document" if iso_raw == "N/A" else "UNCERTAIN"),
            "symbol_seen": symbol_seen,
            "critical_flags": flags,
            "multi_currency_document": bool(raw.get("multi_currency_document")),
            "raw": raw,
            "applied": False,
        }

    if not is_iso4217_currency(iso_raw):
        return {
            **empty,
            "symbol_seen": symbol_seen,
            "critical_flags": flags or ["CRYPTO_OR_NON_ISO"],
            "review_reason": review_reason or f"Non-ISO currency token: {iso_raw}",
            "raw": raw,
            "human_review_required": True,
        }

    if flags or confidence < _MIN_APPLY_CONFIDENCE:
        human_review = True
    if human_review and not review_reason:
        review_reason = "Currency detection requires human review"

    apply = (not human_review) and confidence >= _MIN_APPLY_CONFIDENCE and not flags
    return {
        "iso_code": iso_raw if apply else "",
        "confidence": confidence,
        "human_review_required": human_review or not apply,
        "review_reason": review_reason,
        "symbol_seen": symbol_seen,
        "critical_flags": flags,
        "multi_currency_document": bool(raw.get("multi_currency_document")),
        "raw": raw,
        "applied": apply,
        "candidate_iso": iso_raw,
    }


def apply_currency_detection_to_parsed(
    parsed: InvoiceData,
    detection: dict[str, Any],
) -> InvoiceData:
    """Merge detection result into InvoiceData (currency + audit fields)."""
    extracted = dict(parsed.extracted_fields or {})
    raw_fields = dict(parsed.raw_fields or {})
    audit: dict[str, Any] = {
        "confidence": detection.get("confidence"),
        "human_review_required": detection.get("human_review_required"),
        "review_reason": detection.get("review_reason"),
        "symbol_seen": detection.get("symbol_seen"),
        "critical_flags": detection.get("critical_flags") or [],
        "multi_currency_document": detection.get("multi_currency_document"),
        "applied": detection.get("applied"),
        "candidate_iso": detection.get("candidate_iso") or detection.get("iso_code"),
    }
    doc = (
        (detection.get("raw") or {}).get("document_currency")
        if isinstance(detection.get("raw"), dict)
        else None
    )
    if isinstance(doc, dict):
        audit["decision_basis"] = doc.get("decision_basis")
        audit["evidence"] = doc.get("evidence")
        audit["conflicts"] = doc.get("conflicts")
    raw_fields["currency_detection"] = audit

    updates: dict[str, Any] = {"raw_fields": raw_fields}
    if detection.get("applied") and detection.get("iso_code"):
        updates["currency"] = str(detection["iso_code"]).strip().upper()
        extracted.pop("currency_symbol", None)
        extracted.pop("currency_review_required", None)
        extracted.pop("currency_review_reason", None)
    elif detection.get("symbol_seen") and not (parsed.currency or "").strip():
        extracted["currency_symbol"] = str(detection["symbol_seen"]).strip()
        if detection.get("human_review_required"):
            extracted["currency_review_required"] = True
            if detection.get("review_reason"):
                extracted["currency_review_reason"] = detection["review_reason"]

    if extracted != (parsed.extracted_fields or {}):
        updates["extracted_fields"] = extracted
    return replace(parsed, **updates)


async def detect_document_currency(
    ocr: OcrArtifact,
    *,
    org: OrgContext,
    dt_definition: DocumentTypeDefinition | None = None,
) -> dict[str, Any] | None:
    """Call Currency Detection Agent; return normalized summary or None if skipped."""
    settings = get_settings()
    if not settings.extraction_currency_detect_enabled:
        return None
    if not settings.runtime_llm_available:
        return None
    if not (ocr.text or "").strip():
        return None

    system = resolve_system_prompt_text("llm.currency.system")
    user = build_currency_detect_user_payload(
        ocr=ocr,
        org=org,
        dt_definition=dt_definition,
    )
    try:
        raw = await chat_json_async(
            system=system,
            user=user,
            require_runtime=True,
        )
    except Exception as exc:
        logger.warning("currency_detection_failed", error=str(exc))
        return None
    if not raw:
        return None
    return parse_currency_detection_result(raw)


async def apply_currency_detection(
    parsed: InvoiceData,
    *,
    ocr: OcrArtifact,
    org: OrgContext,
    selected_keys: Sequence[str] | None = None,
    dt_definition: DocumentTypeDefinition | None = None,
) -> tuple[InvoiceData, dict[str, object]]:
    """Run currency agent when needed; return updated parsed + audit detail."""
    detail: dict[str, object] = {
        "currency_detect_attempted": False,
        "currency_detect_applied": False,
        "currency_detect_iso": "",
        "human_review_required": False,
    }
    selected = {
        str(k).strip().lower()
        for k in (selected_keys or [])
        if str(k or "").strip()
    }
    if selected and "currency" not in selected:
        return parsed, detail
    if not currency_detection_needed(parsed):
        return parsed, detail

    detection = await detect_document_currency(
        ocr,
        org=org,
        dt_definition=dt_definition,
    )
    if detection is None:
        return parsed, detail

    detail["currency_detect_attempted"] = True
    detail["currency_detect_applied"] = bool(detection.get("applied"))
    detail["currency_detect_iso"] = str(
        detection.get("iso_code") or detection.get("candidate_iso") or ""
    )
    detail["human_review_required"] = bool(detection.get("human_review_required"))
    detail["review_reason"] = detection.get("review_reason")
    detail["confidence"] = detection.get("confidence")
    detail["critical_flags"] = detection.get("critical_flags") or []

    return apply_currency_detection_to_parsed(parsed, detection), detail
