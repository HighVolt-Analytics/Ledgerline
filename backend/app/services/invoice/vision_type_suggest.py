"""Vision type-suggest — document kind + short summary for DT mapping (no money)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.models.invoice import Invoice
from app.services.extraction.vision_pdf import (
    HEADER_VISION_MAX_PAGES,
    resolve_header_vision_images,
)
from app.services.invoice.vision_header_extract import (
    CANONICAL_DOCUMENT_TYPE_KEY,
    _normalize_perspective,
    derive_canonical_document_type,
)
from app.services.tenant.tenant_org_context import OrgContext
from app.utils.logger import get_logger

if TYPE_CHECKING:
    from app.services.extraction.document_ai_provider import DocumentAiProvider

logger = get_logger(__name__)

DOCUMENT_SUMMARY_KEY = "document_summary"
DOCUMENT_ROLE_HINTS_KEY = "document_role_hints"

VISION_TYPE_SUGGEST_ROLE_HINT_KEYS: tuple[str, ...] = (
    "has_po_reference",
    "has_so_reference",
    "has_invoice_number",
    "is_credit_note",
    "is_supporting_only",
)

VISION_TYPE_SUGGEST_JSON_KEYS: tuple[str, ...] = (
    "document_heading",
    "canonical_document_type",
    "perspective",
    "document_summary",
    "document_role_hints",
    "confidence",
    "reason",
)

VISION_TYPE_SUGGEST_PERSISTED_FIELD_KEYS: tuple[str, ...] = (
    "document_heading",
    "canonical_document_type",
    "perspective",
    DOCUMENT_SUMMARY_KEY,
    DOCUMENT_ROLE_HINTS_KEY,
)

VISION_TYPE_SUGGEST_PROMPT_MARKERS: tuple[str, ...] = (
    "TYPE SUGGEST — understand the document",
    "document_summary",
    "document_role_hints",
    "Do not extract amounts",
    "Do not map to a catalogue DT code",
    "canonical_document_type",
    "SELF-CHECK BEFORE RETURNING",
)

VISION_TYPE_SUGGEST_MIN_CONFIDENCE = 0.55
_SUMMARY_MAX_LEN = 1200


@dataclass(frozen=True)
class VisionTypeSuggestResult:
    success: bool
    document_heading: str = ""
    canonical_document_type: str = ""
    perspective: str = "unknown"
    document_summary: str = ""
    document_role_hints: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    reason: str = ""
    provider: str = ""
    page_count: int = 0
    fail_reason: str | None = None


def vision_type_suggest_audit_detail(result: VisionTypeSuggestResult) -> dict:
    return {
        "success": result.success,
        "document_heading": result.document_heading,
        "canonical_document_type": result.canonical_document_type,
        "perspective": result.perspective,
        "document_summary": result.document_summary,
        "document_role_hints": dict(result.document_role_hints),
        "confidence": result.confidence,
        "reason": result.reason,
        "provider": result.provider,
        "page_count": result.page_count,
        "fail_reason": result.fail_reason,
    }


def document_summary_from_invoice(invoice: Any | None) -> str:
    if invoice is None:
        return ""
    fields = getattr(invoice, "extracted_fields", None)
    if not isinstance(fields, dict):
        return ""
    return str(fields.get(DOCUMENT_SUMMARY_KEY) or "").strip()


def document_role_hints_from_invoice(invoice: Any | None) -> dict[str, str]:
    if invoice is None:
        return {}
    fields = getattr(invoice, "extracted_fields", None)
    if not isinstance(fields, dict):
        return {}
    raw = fields.get(DOCUMENT_ROLE_HINTS_KEY)
    if isinstance(raw, dict):
        return {
            str(k): _normalize_hint_value(v)
            for k, v in raw.items()
            if str(k).strip()
        }
    if isinstance(raw, str) and raw.strip():
        import json

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return {
                str(k): _normalize_hint_value(v)
                for k, v in parsed.items()
                if str(k).strip()
            }
    return {}


def _str_field(raw: dict, key: str) -> str:
    val = raw.get(key)
    if val is None:
        return ""
    return str(val).strip()


def _float_field(raw: dict, key: str, default: float = 0.0) -> float:
    val = raw.get(key)
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _normalize_hint_value(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    text = str(val).strip().lower()
    if text in {"true", "yes", "1"}:
        return "true"
    if text in {"false", "no", "0"}:
        return "false"
    if text in {"", "unknown", "null", "none"}:
        return ""
    return text


def _parse_role_hints(raw: dict) -> dict[str, str]:
    hints_raw = raw.get(DOCUMENT_ROLE_HINTS_KEY)
    out: dict[str, str] = {}
    if isinstance(hints_raw, dict):
        for key in VISION_TYPE_SUGGEST_ROLE_HINT_KEYS:
            if key in hints_raw:
                out[key] = _normalize_hint_value(hints_raw.get(key))
        for key, val in hints_raw.items():
            k = str(key).strip()
            if k and k not in out:
                out[k] = _normalize_hint_value(val)
        return out
    # Flat keys at top level (some providers flatten nested objects)
    for key in VISION_TYPE_SUGGEST_ROLE_HINT_KEYS:
        if key in raw:
            out[key] = _normalize_hint_value(raw.get(key))
    return out


def parse_vision_type_suggest_raw(
    raw: dict | None,
    *,
    provider: str,
    page_count: int,
) -> VisionTypeSuggestResult:
    if not isinstance(raw, dict):
        return VisionTypeSuggestResult(
            success=False,
            provider=provider,
            page_count=page_count,
            fail_reason="empty_response",
        )

    document_heading = _str_field(raw, "document_heading")[:500]
    canonical = derive_canonical_document_type(
        document_heading=document_heading,
        canonical_document_type=_str_field(raw, CANONICAL_DOCUMENT_TYPE_KEY)[:200],
    )
    document_summary = _str_field(raw, DOCUMENT_SUMMARY_KEY)[:_SUMMARY_MAX_LEN]
    role_hints = _parse_role_hints(raw)
    confidence = max(0.0, min(1.0, _float_field(raw, "confidence")))
    has_identity = bool(document_heading or canonical)
    has_summary = bool(document_summary)
    success = (
        has_identity
        and has_summary
        and confidence >= VISION_TYPE_SUGGEST_MIN_CONFIDENCE
    )
    if not success:
        if not has_identity:
            fail_reason = "no_identity"
        elif not has_summary:
            fail_reason = "no_summary"
        else:
            fail_reason = "low_confidence"
    else:
        fail_reason = None
    return VisionTypeSuggestResult(
        success=success,
        document_heading=document_heading,
        canonical_document_type=canonical,
        perspective=_normalize_perspective(_str_field(raw, "perspective")),
        document_summary=document_summary,
        document_role_hints=role_hints,
        confidence=confidence,
        reason=_str_field(raw, "reason")[:500],
        provider=provider,
        page_count=page_count,
        fail_reason=fail_reason,
    )


def _seed_link_refs_from_summary(invoice: Invoice, summary: str) -> None:
    """Best-effort PO/SO column seed from summary text for early classifier/map."""
    from app.services.purchase.po_reference import (
        ensure_invoice_po_reference,
        extract_po_reference_from_text,
        is_plausible_po_reference,
    )
    from app.services.sales.so_reference import (
        ensure_invoice_so_reference,
        extract_so_reference_from_text,
        is_plausible_so_reference,
    )
    from app.services.shared.reference_field_sanitizer import sanitize_reference_for_column

    if not (getattr(invoice, "po_reference", None) or "").strip():
        po = extract_po_reference_from_text(summary)
        if po and is_plausible_po_reference(po):
            invoice.po_reference = sanitize_reference_for_column(
                po, max_len=100, is_plausible=is_plausible_po_reference
            )
    if not (getattr(invoice, "so_reference", None) or "").strip():
        so = extract_so_reference_from_text(summary)
        if so and is_plausible_so_reference(so):
            invoice.so_reference = sanitize_reference_for_column(
                so, max_len=100, is_plausible=is_plausible_so_reference
            )
    ensure_invoice_po_reference(invoice)
    ensure_invoice_so_reference(invoice)


def persist_vision_type_suggest_to_invoice(
    invoice: Invoice,
    result: VisionTypeSuggestResult,
) -> None:
    """Persist kind identity + summary/hints; seed link refs from summary when present."""
    import json

    from app.services.extraction.extraction_field_values import merge_invoice_extracted_fields

    if result.document_heading:
        invoice.document_heading = result.document_heading
    patch: dict[str, Any] = {
        "perspective": result.perspective,
        "llm_perspective": result.perspective,
    }
    if result.document_heading:
        patch["document_heading"] = result.document_heading
    if result.canonical_document_type:
        patch[CANONICAL_DOCUMENT_TYPE_KEY] = result.canonical_document_type
    if result.document_summary:
        patch[DOCUMENT_SUMMARY_KEY] = result.document_summary
    if result.document_role_hints:
        # extracted_fields values are strings — store hints as JSON
        patch[DOCUMENT_ROLE_HINTS_KEY] = json.dumps(
            dict(result.document_role_hints), separators=(",", ":")
        )
    if result.confidence > 0:
        patch["vision_type_suggest_confidence"] = f"{result.confidence:.4f}"
    merge_invoice_extracted_fields(invoice, patch)
    if result.document_summary:
        _seed_link_refs_from_summary(invoice, result.document_summary)


async def evaluate_vision_type_suggest(
    file_path: str | Path,
    *,
    provider: DocumentAiProvider,
    org: OrgContext,
    vision_page_images: list[bytes] | None = None,
) -> VisionTypeSuggestResult:
    """Rasterize + call type-suggest with summary; never raises."""
    from app.services.extraction.document_ai_provider import (
        DocumentAiProvider as _DocumentAiProvider,
        extract_vision_type_suggest,
        provider_available,
        provider_unavailable_reason,
    )

    provider_token = provider.value
    if provider not in (
        _DocumentAiProvider.GEMINI_VISION,
        _DocumentAiProvider.AZURE_FOUNDRY_VISION,
        _DocumentAiProvider.CLAUDE_VISION,
    ):
        return VisionTypeSuggestResult(
            success=False,
            provider=provider_token,
            fail_reason="vision_provider_not_configured",
        )
    if not provider_available(provider):
        return VisionTypeSuggestResult(
            success=False,
            provider=provider_token,
            fail_reason=provider_unavailable_reason(provider) or "vision_unavailable",
        )

    path = Path(file_path)
    try:
        images = resolve_header_vision_images(
            path,
            vision_page_images,
            max_pages=HEADER_VISION_MAX_PAGES,
        )
    except Exception as exc:
        logger.warning("vision_type_suggest_raster_failed", error=str(exc))
        return VisionTypeSuggestResult(
            success=False,
            provider=provider_token,
            fail_reason="rasterize_failed",
        )
    if not images:
        return VisionTypeSuggestResult(
            success=False,
            provider=provider_token,
            fail_reason="no_pages",
        )

    try:
        raw = await extract_vision_type_suggest(
            provider=provider,
            images=images,
            org=org,
        )
    except Exception as exc:
        logger.warning("vision_type_suggest_failed", error=str(exc))
        return VisionTypeSuggestResult(
            success=False,
            provider=provider_token,
            page_count=len(images),
            fail_reason="provider_error",
        )

    return parse_vision_type_suggest_raw(
        raw,
        provider=provider_token,
        page_count=len(images),
    )
