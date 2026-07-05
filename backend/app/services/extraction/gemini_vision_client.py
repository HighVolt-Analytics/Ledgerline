"""Gemini 2.5 Vision — OCR read, classify, and extract as separate phases."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Sequence

import httpx

from app.config import get_settings
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.services.classification.document_type_field_keys import CANONICAL_EXTRACTION_FIELD_KEYS
from app.services.extraction.extraction_field_values import (
    custom_extraction_field_descriptors,
    custom_extraction_field_keys,
    custom_extraction_field_keys_for_dt,
    custom_extraction_fields_prompt_lines,
)
from app.services.extraction.party_field_service import PARTY_LLM_RULES
from app.services.extraction.llm_document_service import _normalize_llm_raw
from app.services.tenant.tenant_org_context import OrgContext
from app.services.extraction.vision_pdf import pdf_page_images
from app.utils.logger import get_logger

logger = get_logger(__name__)

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

_GEMINI_CLASSIFY_SYSTEM = """You classify finance documents for accounts payable from document images.
Return JSON only with keys:
suggested_dt, confidence, reasoning, perspective, seller, buyer, document_heading.

Rules:
- suggested_dt must be one of the catalogue codes provided, or empty string if unsure.
- confidence is 0.0-1.0 for the document type choice.
- perspective is purchase | sales | unknown.
""" + PARTY_LLM_RULES + """
- Do not extract invoice amounts, line items, or dates — classification only.
- few_shot_examples are prior reviewer corrections. When document_heading or text_excerpt
  closely matches a few-shot example, strongly prefer that example's human_confirmed_dt.
- Examples with vendor_key match the sender/vendor — prefer those when the layout matches that supplier."""


def is_gemini_vision_available() -> bool:
    return get_settings().gemini_vision_available


def _catalogue_rows(document_types: Sequence[DocumentTypeDefinition]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for defn in document_types:
        if not defn.enabled:
            continue
        hint = getattr(defn, "llm_hint", None) or ""
        rows.append(
            {
                "code": defn.code.strip().upper(),
                "title": defn.title,
                "one_line": defn.one_line,
                "llm_hint": str(hint).strip(),
            }
        )
    return rows


async def _generate_json(
    *,
    system: str,
    user_parts: list[dict[str, Any]],
    timeout_seconds: int,
) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.gemini_configured:
        return None

    model = settings.gemini_vision_model.strip() or "gemini-2.5-flash"
    url = f"{_GEMINI_BASE}/models/{model}:generateContent"
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": user_parts}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                url,
                params={"key": settings.google_gemini_api_key.strip()},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
    except Exception as exc:
        logger.warning("gemini_vision_request_failed", error=str(exc))
        return None

    candidates = body.get("candidates") or []
    if not candidates:
        return None
    parts = (candidates[0].get("content") or {}).get("parts") or []
    if not parts:
        return None
    text = parts[0].get("text") or ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("gemini_vision_invalid_json")
        return None


def _image_parts(images: list[bytes]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for image in images:
        parts.append(
            {
                "inlineData": {
                    "mimeType": "image/png",
                    "data": base64.b64encode(image).decode("ascii"),
                }
            }
        )
    return parts


async def read_for_classification_gemini(
    file_path: str | Path,
    *,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
) -> OcrArtifact:
    """Vision OCR only — headings/text excerpt, no document-type classification."""
    settings = get_settings()
    path = Path(file_path)
    images = pdf_page_images(path)
    if not images:
        raise ValueError("gemini_no_pages")

    system = """You read finance document images for accounts payable OCR.
Return JSON only with keys: document_heading, text_excerpt.
- document_heading is the primary visible document title or heading.
- text_excerpt is plain text of visible headings and key labels (max 2000 chars)."""

    user_text = json.dumps(
        {
            "tenant": {
                "legal_name": org.legal_name,
                "abn": org.abn,
            },
        },
        default=str,
    )
    parts = _image_parts(images)
    parts.append({"text": user_text})

    raw = await _generate_json(
        system=system,
        user_parts=parts,
        timeout_seconds=settings.runtime_llm_timeout_seconds,
    )
    if raw is None:
        raise ValueError("gemini_read_failed")

    excerpt = str(raw.get("text_excerpt") or raw.get("document_heading") or "").strip()
    text_length = len(excerpt)
    sparse = text_length < settings.ocr_min_text_chars
    return OcrArtifact(
        success=True,
        sparse=sparse,
        text=excerpt,
        text_length=text_length,
        di_model=settings.gemini_vision_model,
        layout_kv={},
        payload_json={
            "provider": "gemini_vision",
            "document_heading": str(raw.get("document_heading") or "").strip(),
            "page_count": len(images),
        },
    )


async def classify_only_gemini(
    file_path: str | Path,
    ocr: OcrArtifact,
    *,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    few_shots: Sequence[dict[str, str]] | None = None,
) -> LlmDocumentResult | None:
    """Separate classify step with catalogue + few-shots (post-OCR)."""
    settings = get_settings()
    path = Path(file_path)
    images = pdf_page_images(path)
    if not images:
        return None

    user_text = json.dumps(
        {
            "tenant": {
                "legal_name": org.legal_name,
                "abn": org.abn,
                "default_perspective": org.default_perspective,
            },
            "catalogue": _catalogue_rows(document_types),
            "few_shot_examples": list(few_shots or [])[:5],
            "ocr": {
                "text_excerpt": (ocr.text or "")[:12000],
                "document_heading": ocr.payload_json.get("document_heading"),
                "text_length": ocr.text_length,
            },
        },
        default=str,
    )
    parts = _image_parts(images)
    parts.append({"text": user_text})

    raw = await _generate_json(
        system=_GEMINI_CLASSIFY_SYSTEM,
        user_parts=parts,
        timeout_seconds=settings.runtime_llm_timeout_seconds,
    )
    if raw is None:
        return None
    try:
        result = LlmDocumentResult.model_validate(raw)
        result.raw = raw
        return result
    except Exception as exc:
        logger.warning("gemini_classify_invalid", error=str(exc))
        return None


async def extract_fields_gemini(
    file_path: str | Path,
    *,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    confirmed_dt: str,
    few_shots: Sequence[dict[str, str]] | None = None,
) -> LlmDocumentResult | None:
    settings = get_settings()
    path = Path(file_path)
    images = pdf_page_images(path)
    if not images:
        return None

    dt_token = confirmed_dt.strip().upper()
    custom_keys = custom_extraction_field_keys_for_dt(document_types, dt_token)
    if not custom_keys:
        custom_keys = custom_extraction_field_keys(document_types)

    descriptors = custom_extraction_field_descriptors(custom_keys)
    custom_hint = ""
    if descriptors:
        custom_hint = "\n" + "\n".join(custom_extraction_fields_prompt_lines(descriptors))

    system = f"""You extract accounts-payable fields from finance document images.
Return JSON only with keys:
suggested_dt, confidence, reasoning, perspective,
seller, buyer, invoice_no, invoice_date, due_date, po_reference,
subtotal, gst, gst_rate, total, currency, abn, vendor, document_heading,
bank_bsb, bank_account, bank_name, line_items, field_confidence, extracted_fields.
Use confirmed_dt as suggested_dt. Extract faithfully from the images.
- line_items must be product/service rows only — never header metadata (Customer, Ship Date, Invoice No, BSB, etc.).
- If a row is a field label ending with ":" it is NOT a line item.
- bank_bsb, bank_account, bank_name: extract only when explicitly labeled. Leave empty if absent.
{PARTY_LLM_RULES}{custom_hint}"""

    user_text = json.dumps(
        {
            "confirmed_dt": dt_token,
            "tenant": {
                "legal_name": org.legal_name,
                "abn": org.abn,
            },
            "catalogue": _catalogue_rows(document_types),
            "few_shot_examples": list(few_shots or [])[:5],
            "custom_extraction_fields": custom_keys,
            "custom_extraction_field_descriptors": descriptors,
            "canonical_extraction_fields": sorted(CANONICAL_EXTRACTION_FIELD_KEYS),
        },
        default=str,
    )
    parts = _image_parts(images)
    parts.append({"text": user_text})

    raw = await _generate_json(
        system=system,
        user_parts=parts,
        timeout_seconds=settings.runtime_llm_timeout_seconds,
    )
    if raw is None:
        return None
    try:
        normalized = _normalize_llm_raw(raw, custom_keys=custom_keys)
        normalized["suggested_dt"] = dt_token
        result = LlmDocumentResult.model_validate(normalized)
        result.raw = raw
        return result
    except Exception as exc:
        logger.warning("gemini_extract_invalid", error=str(exc))
        return None
