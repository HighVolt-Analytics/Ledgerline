"""Focused second-pass LLM extraction for configured fields still missing after main pipeline."""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from pydantic import ValidationError

from app.config import get_settings
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.azure_openai_client import chat_json_async
from app.services.extraction.extraction_field_values import (
    build_extraction_field_manifest,
    build_field_ocr_snippets,
    build_smart_ocr_excerpt,
    extraction_accuracy_prompt_lines,
    merge_gap_fill_into_parsed,
    missing_configured_extraction_keys,
    non_canonical_extraction_keys,
)
from app.services.extraction.llm_document_service import (
    _normalize_llm_raw,
    build_llm_extract_json_keys,
    llm_result_to_invoice_data,
)
from app.services.invoice.invoice_data import InvoiceData
from app.services.tenant.tenant_org_context import OrgContext
from app.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.models.invoice import Invoice
    from app.schemas.document_type import DocumentTypeDefinition

logger = get_logger(__name__)

_GAP_FILL_SYSTEM_HEADER = """You fill ONLY the missing_fields listed in the user payload from OCR text.
Return JSON only with the keys listed in the response schema.

Rules:
1. Copy values verbatim from ocr.text_excerpt or field_snippets — nothing else.
2. If a field is not explicitly present in OCR, return empty ("" or omit). Do NOT guess.
3. Never infer, calculate, or assume (no currency default, no date math, no vendor from email domain).
4. Never swap semantically similar fields (invoice_no ≠ po_reference, vendor ≠ buyer).
5. field_confidence: 0.0 when empty; 0.95+ only for verbatim OCR copies.
6. Put custom (non-canonical) string values in extracted_fields.{key}.
7. invoice_date and due_date must be ISO YYYY-MM-DD when present in OCR.
"""


def build_gap_fill_system_prompt(*, missing_keys: Sequence[str]) -> str:
    json_keys = build_llm_extract_json_keys(missing_keys)
    parts = [
        _GAP_FILL_SYSTEM_HEADER.strip(),
        f"\nReturn JSON only with keys:\n{json_keys}.",
    ]
    parts.extend(extraction_accuracy_prompt_lines())
    return "\n".join(parts)


def build_gap_fill_user_payload(
    *,
    ocr: OcrArtifact,
    missing_keys: Sequence[str],
    snippets: dict[str, str] | None = None,
    descriptors: list[dict[str, str]] | None = None,
) -> str:
    missing = [str(key or "").strip().lower() for key in missing_keys if str(key or "").strip()]
    snippet_map = snippets if snippets is not None else build_field_ocr_snippets(ocr.text, missing)
    field_rows = descriptors if descriptors is not None else build_extraction_field_manifest(missing)
    payload: dict[str, Any] = {
        "missing_fields": missing,
        "field_descriptors": field_rows,
        "field_snippets": snippet_map,
        "ocr": {
            "text_excerpt": build_smart_ocr_excerpt(ocr.text),
            "text_length": ocr.text_length,
        },
    }
    return json.dumps(payload, default=str)


async def gap_fill_missing_fields(
    ocr: OcrArtifact,
    *,
    missing_keys: Sequence[str],
    org: OrgContext,
    dt_definition: DocumentTypeDefinition | None = None,
) -> InvoiceData | None:
    """Second-pass LLM extract for keys still empty; returns InvoiceData or None if skipped."""
    _ = dt_definition
    settings = get_settings()
    if not settings.extraction_gap_fill_enabled:
        return None
    if not settings.runtime_llm_available:
        return None
    missing = [str(key or "").strip().lower() for key in missing_keys if str(key or "").strip()]
    if not missing:
        return None
    if not (ocr.text or "").strip():
        return None

    system = build_gap_fill_system_prompt(missing_keys=missing)
    user = build_gap_fill_user_payload(ocr=ocr, missing_keys=missing)
    raw = await chat_json_async(
        system=system,
        user=user,
        timeout_seconds=settings.runtime_llm_timeout_seconds,
        require_runtime=True,
    )
    if raw is None:
        return None

    custom_keys = non_canonical_extraction_keys(missing)
    try:
        normalized = _normalize_llm_raw(
            raw,
            selected_keys=missing,
            custom_keys=custom_keys,
        )
        llm = LlmDocumentResult.model_validate(normalized)
        llm.raw = raw
    except ValidationError as exc:
        logger.warning("gap_fill_invalid", error=str(exc))
        return None

    return llm_result_to_invoice_data(
        llm,
        ocr=ocr,
        custom_keys=custom_keys or None,
        selected_keys=missing,
        org=org,
    )


async def apply_extraction_gap_fill(
    parsed: InvoiceData,
    *,
    ocr: OcrArtifact,
    selected_keys: Sequence[str],
    org: OrgContext,
    dt_definition: DocumentTypeDefinition | None = None,
    invoice: Invoice | None = None,
) -> tuple[InvoiceData, dict[str, object]]:
    """Run gap-fill when configured keys are still empty; return parsed + audit detail."""
    settings = get_settings()
    missing = missing_configured_extraction_keys(
        selected_keys,
        parsed=parsed,
        invoice=invoice,
    )
    detail: dict[str, object] = {
        "gap_fill_attempted": False,
        "gap_fill_keys": list(missing),
        "gap_fill_filled": [],
        "gap_fill_rejected": [],
    }
    if not missing or not settings.extraction_gap_fill_enabled or not settings.runtime_llm_available:
        return parsed, detail
    if not (ocr.text or "").strip():
        return parsed, detail

    detail["gap_fill_attempted"] = True
    gap = await gap_fill_missing_fields(
        ocr,
        missing_keys=missing,
        org=org,
        dt_definition=dt_definition,
    )
    if gap is None:
        return parsed, detail

    merge_result = merge_gap_fill_into_parsed(
        parsed,
        gap,
        missing_keys=missing,
        ocr_text=ocr.text,
    )
    detail["gap_fill_filled"] = list(merge_result.filled)
    detail["gap_fill_rejected"] = list(merge_result.rejected)
    return merge_result.parsed, detail
