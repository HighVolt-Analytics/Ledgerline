"""Dedicated Field Translation Agent (llm.field_translate.system).

Runs after extraction/grounding. Writes English into human-readable fields and
stores original-language values in extracted_fields for audit.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any, TYPE_CHECKING

from app.config import get_settings
from app.services.extraction.azure_openai_client import chat_json_async
from app.services.extraction.extraction_field_values import build_smart_ocr_excerpt
from app.services.invoice.invoice_data import InvoiceData, ParsedLineItem
from app.services.prompt_registry import resolve_system_prompt_text
from app.utils.logger import get_logger

if TYPE_CHECKING:
    from app.services.invoice.vision_header_extract import VisionHeaderExtractResult

logger = get_logger(__name__)

_MIN_APPLY_CONFIDENCE = 0.85
_MIN_APPLY_CONFIDENCE_NON_LATIN = 0.70
_ENGLISH_CODES = frozenset({"en", "eng", "en-us", "en-gb", "en-au", "en-in", "en-nz", "en-ca"})

# Identity / numeric / party — never send as translation candidates.
_NEVER_TRANSLATE_KEYS = frozenset(
    {
        "vendor",
        "abn",
        "invoice_no",
        "invoice_date",
        "due_date",
        "po_reference",
        "so_reference",
        "grn_reference",
        "remittance_reference",
        "statement_reference",
        "cost_centre",
        "subtotal",
        "gst",
        "gst_rate",
        "total",
        "currency",
        "billing_address",
        "bank_bsb",
        "bank_account",
        "employee_name",
        "seller_name",
        "seller_tax_id",
        "seller_address",
        "seller_abn",
        "buyer_name",
        "buyer_tax_id",
        "buyer_address",
        "buyer_abn",
        "account_code",
        "account_name",
        "bank_name",
        "proforma_invoice_no",
        "other_reference",
        "email_sender",
        "email_subject",
        "attachment_name",
        "canonical_document_type",
        "perspective",
        "llm_perspective",
        "counterparty_name",
    }
)

_META_KEY_PREFIXES = ("original_", "translation_")
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)
_LATIN_SCRIPTS = frozenset({"LATIN", "COMMON", "INHERITED"})


def _has_non_latin_letters(text: str | None) -> bool:
    """True when text contains letters outside the Latin script family."""
    from app.services.extraction.ocr_quality_signals import count_letter_scripts

    counts = count_letter_scripts(text)
    return any(script not in _LATIN_SCRIPTS and n > 0 for script, n in counts.items())


def _is_meta_key(key: str) -> bool:
    token = (key or "").strip().lower()
    return any(token.startswith(prefix) for prefix in _META_KEY_PREFIXES) or token in {
        "line_item_description_originals",
        "translation_source_language",
        "translation_applied",
        "translation_confidence",
        "translation_skip_reason",
    }


def _looks_translatable_text(value: str) -> bool:
    text = (value or "").strip()
    if len(text) < 2:
        return False
    if not _LETTER_RE.search(text):
        return False
    # Skip pure identifiers / codes (mostly digits + separators).
    letters = sum(1 for ch in text if ch.isalpha())
    if letters < 2:
        return False
    return True


def collect_translation_candidates(
    *,
    document_heading: str | None,
    line_items: list[ParsedLineItem] | tuple[ParsedLineItem, ...] | None,
    extracted_fields: dict[str, str] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Return (fields_map, line_descriptions) candidates for the agent."""
    fields: dict[str, str] = {}
    heading = (document_heading or "").strip()
    if _looks_translatable_text(heading):
        fields["document_heading"] = heading

    for key, raw in (extracted_fields or {}).items():
        token = str(key or "").strip().lower()
        if not token or token in _NEVER_TRANSLATE_KEYS or _is_meta_key(token):
            continue
        if token == "document_heading":
            continue
        value = str(raw or "").strip()
        if _looks_translatable_text(value):
            fields[token] = value

    lines: list[str] = []
    for item in line_items or ():
        desc = (getattr(item, "description", None) or "").strip()
        lines.append(desc)
    return fields, lines


def translation_needed(
    *,
    document_heading: str | None = None,
    line_items: list[ParsedLineItem] | tuple[ParsedLineItem, ...] | None = None,
    extracted_fields: dict[str, str] | None = None,
    context_text: str | None = None,
) -> bool:
    fields, lines = collect_translation_candidates(
        document_heading=document_heading,
        line_items=line_items,
        extracted_fields=extracted_fields,
    )
    if not fields and not any((d or "").strip() for d in lines):
        return False
    # Context optional but preferred; allow when candidates exist even if context empty.
    del context_text
    return True


def build_translation_user_payload(
    *,
    context_text: str,
    fields: dict[str, str],
    line_descriptions: list[str],
) -> str:
    excerpt = build_smart_ocr_excerpt(context_text or "")
    payload: dict[str, Any] = {
        "document_context": excerpt,
        "fields": fields,
        "line_descriptions": line_descriptions,
    }
    return json.dumps(payload, default=str, ensure_ascii=False)


def parse_translation_result(
    raw: dict[str, Any] | None,
    *,
    input_fields: dict[str, str],
    input_lines: list[str],
) -> dict[str, Any]:
    """Normalize agent JSON into an apply-ready summary."""
    empty: dict[str, Any] = {
        "source_language": "",
        "confidence": 0.0,
        "fields": {},
        "line_descriptions": [],
        "skip_reason": "Translation returned no usable payload",
        "applied": False,
        "raw": raw or {},
    }
    if not isinstance(raw, dict):
        return empty

    source_language = str(raw.get("source_language") or "").strip().lower()
    try:
        confidence = float(raw.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    skip_reason = str(raw.get("skip_reason") or "").strip()

    out_fields_raw = raw.get("fields")
    out_fields: dict[str, str] = {}
    if isinstance(out_fields_raw, dict):
        for key, value in out_fields_raw.items():
            token = str(key or "").strip().lower()
            if token not in input_fields:
                continue
            text = str(value or "").strip()
            if not text:
                continue
            # Keep only when translation actually changes the value.
            if text != (input_fields.get(token) or "").strip():
                out_fields[token] = text

    out_lines_raw = raw.get("line_descriptions")
    out_lines: list[str] = []
    if isinstance(out_lines_raw, list) and len(out_lines_raw) == len(input_lines):
        for idx, value in enumerate(out_lines_raw):
            text = str(value if value is not None else "").strip()
            original = (input_lines[idx] or "").strip()
            if not original:
                out_lines.append("")
                continue
            out_lines.append(text if text else original)

    already_english = source_language in _ENGLISH_CODES
    # Model sometimes mislabels non-Latin headings as English — never skip those.
    if already_english and (
        any(_has_non_latin_letters(v) for v in input_fields.values())
        or any(_has_non_latin_letters(v) for v in input_lines)
    ):
        already_english = False
        source_language = source_language if source_language not in _ENGLISH_CODES else "und"
        skip_reason = ""

    if already_english:
        return {
            "source_language": source_language or "en",
            "confidence": confidence,
            "fields": {},
            "line_descriptions": [],
            "skip_reason": skip_reason or "already_english",
            "applied": False,
            "raw": raw,
        }

    lines_changed = bool(out_lines) and any(
        (out_lines[i] or "").strip() != (input_lines[i] or "").strip()
        for i in range(len(input_lines))
        if (input_lines[i] or "").strip()
    )
    has_work = bool(out_fields) or lines_changed
    if not has_work:
        return {
            "source_language": source_language,
            "confidence": confidence,
            "fields": {},
            "line_descriptions": [],
            "skip_reason": skip_reason or "no_translation_changes",
            "applied": False,
            "raw": raw,
        }

    has_non_latin = any(_has_non_latin_letters(v) for v in input_fields.values()) or any(
        _has_non_latin_letters(v) for v in input_lines
    )
    min_confidence = (
        _MIN_APPLY_CONFIDENCE_NON_LATIN if has_non_latin else _MIN_APPLY_CONFIDENCE
    )
    if confidence < min_confidence:
        return {
            "source_language": source_language,
            "confidence": confidence,
            "fields": {},
            "line_descriptions": [],
            "skip_reason": skip_reason or "confidence_below_threshold",
            "applied": False,
            "raw": raw,
        }

    return {
        "source_language": source_language,
        "confidence": confidence,
        "fields": out_fields,
        "line_descriptions": out_lines if lines_changed else [],
        "skip_reason": "",
        "applied": True,
        "raw": raw,
    }


def _merge_originals_into_extracted(
    extracted: dict[str, str],
    *,
    originals: dict[str, str],
    line_originals: list[str] | None,
    source_language: str,
    confidence: float,
) -> dict[str, str]:
    merged = dict(extracted)
    for key, value in originals.items():
        if key == "document_heading":
            merged["original_document_heading"] = value
        else:
            merged[f"original_{key}"] = value
    if line_originals is not None:
        merged["line_item_description_originals"] = json.dumps(
            line_originals, ensure_ascii=False
        )
    if source_language:
        merged["translation_source_language"] = source_language
    merged["translation_applied"] = "true"
    merged["translation_confidence"] = f"{confidence:.4f}"
    return merged


def apply_translation_detection_to_parsed(
    parsed: InvoiceData,
    detection: dict[str, Any],
) -> InvoiceData:
    """Merge translation result into InvoiceData (English primary + originals)."""
    if not detection.get("applied"):
        extracted = dict(parsed.extracted_fields or {})
        if detection.get("source_language"):
            extracted["translation_source_language"] = str(detection["source_language"])
        if detection.get("skip_reason"):
            extracted["translation_skip_reason"] = str(detection["skip_reason"])[:200]
        extracted["translation_applied"] = "false"
        return replace(parsed, extracted_fields=extracted)

    fields_en: dict[str, str] = dict(detection.get("fields") or {})
    lines_en: list[str] = list(detection.get("line_descriptions") or [])
    originals: dict[str, str] = {}

    updates: dict[str, Any] = {}
    extracted = dict(parsed.extracted_fields or {})

    if "document_heading" in fields_en:
        original = (parsed.document_heading or "").strip()
        if original:
            originals["document_heading"] = original
        updates["document_heading"] = fields_en["document_heading"]

    for key, en_value in fields_en.items():
        if key == "document_heading":
            continue
        original = str((parsed.extracted_fields or {}).get(key) or "").strip()
        if original:
            originals[key] = original
        extracted[key] = en_value

    new_lines = list(parsed.line_items or [])
    line_originals: list[str] | None = None
    if lines_en and len(lines_en) == len(new_lines):
        line_originals = []
        rebuilt: list[ParsedLineItem] = []
        for idx, item in enumerate(new_lines):
            original_desc = (item.description or "").strip()
            line_originals.append(original_desc)
            en_desc = (lines_en[idx] or "").strip()
            if original_desc and en_desc and en_desc != original_desc:
                rebuilt.append(replace(item, description=en_desc))
            else:
                rebuilt.append(item)
        updates["line_items"] = rebuilt

    extracted = _merge_originals_into_extracted(
        extracted,
        originals=originals,
        line_originals=line_originals,
        source_language=str(detection.get("source_language") or ""),
        confidence=float(detection.get("confidence") or 0.0),
    )
    updates["extracted_fields"] = extracted

    raw_fields = dict(parsed.raw_fields or {})
    raw_fields["field_translation"] = {
        "applied": True,
        "source_language": detection.get("source_language"),
        "confidence": detection.get("confidence"),
        "translated_keys": sorted(fields_en.keys()),
        "line_count": len(line_originals or []),
    }
    updates["raw_fields"] = raw_fields
    return replace(parsed, **updates)


def apply_translation_detection_to_vision_header(
    result: VisionHeaderExtractResult,
    detection: dict[str, Any],
) -> tuple[VisionHeaderExtractResult, dict[str, str]]:
    """Apply English translations onto vision header result; return originals patch."""
    originals_patch: dict[str, str] = {
        "translation_applied": "false",
    }
    if detection.get("source_language"):
        originals_patch["translation_source_language"] = str(detection["source_language"])
    if detection.get("skip_reason"):
        originals_patch["translation_skip_reason"] = str(detection["skip_reason"])[:200]

    if not detection.get("applied"):
        return result, originals_patch

    fields_en: dict[str, str] = dict(detection.get("fields") or {})
    lines_en: list[str] = list(detection.get("line_descriptions") or [])
    originals: dict[str, str] = {}
    updates: dict[str, Any] = {}

    if "document_heading" in fields_en:
        original = (result.document_heading or "").strip()
        if original:
            originals["document_heading"] = original
        updates["document_heading"] = fields_en["document_heading"]

    new_lines = list(result.line_items or ())
    line_originals: list[str] | None = None
    if lines_en and len(lines_en) == len(new_lines):
        line_originals = []
        rebuilt: list[ParsedLineItem] = []
        for idx, item in enumerate(new_lines):
            original_desc = (item.description or "").strip()
            line_originals.append(original_desc)
            en_desc = (lines_en[idx] or "").strip()
            if original_desc and en_desc and en_desc != original_desc:
                rebuilt.append(replace(item, description=en_desc))
            else:
                rebuilt.append(item)
        updates["line_items"] = tuple(rebuilt)

    if not updates:
        return result, originals_patch

    updated = replace(result, **updates)
    originals_patch = _merge_originals_into_extracted(
        {},
        originals=originals,
        line_originals=line_originals,
        source_language=str(detection.get("source_language") or ""),
        confidence=float(detection.get("confidence") or 0.0),
    )
    return updated, originals_patch


async def detect_field_translations(
    *,
    context_text: str,
    fields: dict[str, str],
    line_descriptions: list[str],
) -> dict[str, Any] | None:
    """Call Field Translation Agent; return normalized summary or None if skipped."""
    settings = get_settings()
    if not settings.auto_translate_extracted_fields:
        return None
    if not settings.runtime_llm_available:
        return None
    if not fields and not any((d or "").strip() for d in line_descriptions):
        return None

    system = resolve_system_prompt_text("llm.field_translate.system")
    user = build_translation_user_payload(
        context_text=context_text,
        fields=fields,
        line_descriptions=line_descriptions,
    )
    try:
        raw = await chat_json_async(
            system=system,
            user=user,
            require_runtime=True,
        )
    except Exception as exc:
        logger.warning("field_translation_failed", error=str(exc))
        return None
    if not raw:
        return None
    return parse_translation_result(
        raw,
        input_fields=fields,
        input_lines=line_descriptions,
    )


async def apply_field_translation(
    parsed: InvoiceData,
    *,
    context_text: str,
    path: str = "not_understood",
) -> tuple[InvoiceData, dict[str, object]]:
    """Run translation agent when needed; return updated parsed + audit detail."""
    detail: dict[str, object] = {
        "field_translation_attempted": False,
        "field_translation_applied": False,
        "path": path,
        "source_language": "",
        "confidence": 0.0,
        "translated_keys": [],
    }
    settings = get_settings()
    if not settings.auto_translate_extracted_fields:
        detail["skip_reason"] = "disabled"
        return parsed, detail

    fields, lines = collect_translation_candidates(
        document_heading=parsed.document_heading,
        line_items=parsed.line_items,
        extracted_fields=parsed.extracted_fields,
    )
    if not translation_needed(
        document_heading=parsed.document_heading,
        line_items=parsed.line_items,
        extracted_fields=parsed.extracted_fields,
        context_text=context_text,
    ):
        detail["skip_reason"] = "no_candidates"
        return parsed, detail

    detection = await detect_field_translations(
        context_text=context_text or parsed.document_text or "",
        fields=fields,
        line_descriptions=lines,
    )
    if detection is None:
        detail["skip_reason"] = "agent_unavailable"
        return parsed, detail

    detail["field_translation_attempted"] = True
    detail["source_language"] = str(detection.get("source_language") or "")
    detail["confidence"] = float(detection.get("confidence") or 0.0)
    detail["skip_reason"] = str(detection.get("skip_reason") or "")
    updated = apply_translation_detection_to_parsed(parsed, detection)
    detail["field_translation_applied"] = bool(detection.get("applied"))
    detail["translated_keys"] = sorted((detection.get("fields") or {}).keys())
    if detection.get("line_descriptions"):
        detail["translated_line_count"] = len(
            [
                1
                for i, desc in enumerate(detection["line_descriptions"])
                if (desc or "").strip()
                and i < len(lines)
                and (desc or "").strip() != (lines[i] or "").strip()
            ]
        )
    return updated, detail


async def apply_field_translation_to_vision_header(
    result: VisionHeaderExtractResult,
    *,
    context_text: str,
) -> tuple[VisionHeaderExtractResult, dict[str, object], dict[str, str]]:
    """Translate vision header fields; return (result, audit_detail, extracted_fields_patch)."""
    detail: dict[str, object] = {
        "field_translation_attempted": False,
        "field_translation_applied": False,
        "path": "understood",
        "source_language": "",
        "confidence": 0.0,
        "translated_keys": [],
    }
    empty_patch: dict[str, str] = {}
    settings = get_settings()
    if not settings.auto_translate_extracted_fields:
        detail["skip_reason"] = "disabled"
        return result, detail, empty_patch
    if not result.success:
        detail["skip_reason"] = "vision_header_failed"
        return result, detail, empty_patch

    fields, lines = collect_translation_candidates(
        document_heading=result.document_heading,
        line_items=list(result.line_items or ()),
        extracted_fields=None,
    )
    if not translation_needed(
        document_heading=result.document_heading,
        line_items=list(result.line_items or ()),
        context_text=context_text,
    ):
        detail["skip_reason"] = "no_candidates"
        return result, detail, empty_patch

    detection = await detect_field_translations(
        context_text=context_text or "",
        fields=fields,
        line_descriptions=lines,
    )
    if detection is None:
        detail["skip_reason"] = "agent_unavailable"
        return result, detail, empty_patch

    detail["field_translation_attempted"] = True
    detail["source_language"] = str(detection.get("source_language") or "")
    detail["confidence"] = float(detection.get("confidence") or 0.0)
    detail["skip_reason"] = str(detection.get("skip_reason") or "")
    updated, patch = apply_translation_detection_to_vision_header(result, detection)
    detail["field_translation_applied"] = bool(detection.get("applied"))
    detail["translated_keys"] = sorted((detection.get("fields") or {}).keys())
    return updated, detail, patch
