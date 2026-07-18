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
from app.services.extraction.party_field_service import party_llm_rules
from app.services.prompt_registry import resolve_system_prompt_text
from app.services.extraction.llm_catalogue_rows import build_llm_catalogue_rows
from app.services.extraction.extraction_field_values import non_canonical_extraction_keys
from app.services.extraction.llm_document_service import (
    _normalize_llm_raw,
    _selected_keys_for_dt,
    build_structure_extract_prompts,
)
from app.services.tenant.tenant_org_context import OrgContext
from app.services.extraction.vision_pdf import resolve_pdf_page_images
from app.utils.logger import get_logger

logger = get_logger(__name__)

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

def is_gemini_vision_available() -> bool:
    return get_settings().gemini_vision_available


def _catalogue_rows(document_types: Sequence[DocumentTypeDefinition]) -> list[dict[str, Any]]:
    return build_llm_catalogue_rows(document_types)


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
    from app.services.extraction.vision_pdf import sniff_image_media_type

    parts: list[dict[str, Any]] = []
    for image in images:
        parts.append(
            {
                "inlineData": {
                    "mimeType": sniff_image_media_type(image),
                    "data": base64.b64encode(image).decode("ascii"),
                }
            }
        )
    return parts


async def probe_understand_gemini(images: list[bytes]) -> dict[str, Any] | None:
    """Lightweight yes/no understandability check — not classify/extract."""
    settings = get_settings()
    if not images:
        return None
    parts = _image_parts(images)
    parts.append(
        {
            "text": json.dumps(
                {
                    "task": "vision_understand",
                    "instruction": (
                        "Decide whether you can clearly read and understand this "
                        "finance document well enough to extract key fields later."
                    ),
                }
            )
        }
    )
    return await _generate_json(
        system=resolve_system_prompt_text("vision.understand.system"),
        user_parts=parts,
        timeout_seconds=settings.runtime_llm_timeout_seconds,
    )


def _org_tenant_block(org: OrgContext) -> dict[str, Any]:
    return {
        "legal_name": org.legal_name,
        "abn": org.abn,
        "aliases": list(org.aliases or []),
        "default_perspective": org.default_perspective,
        "intake_summary": org.intake_summary,
    }


def _vision_header_user_payload(org: OrgContext) -> dict[str, Any]:
    from app.services.invoice.vision_header_schema import VISION_HEADER_JSON_KEYS

    return {
        "task": "vision_header_extract",
        "required_keys": list(VISION_HEADER_JSON_KEYS),
        "tenant": _org_tenant_block(org),
    }


async def extract_header_gemini(
    images: list[bytes],
    *,
    org: OrgContext,
) -> dict[str, Any] | None:
    """Header identity extract: printed title, counterparty, linking refs."""
    settings = get_settings()
    if not images:
        return None
    parts = _image_parts(images)
    parts.append(
        {
            "text": json.dumps(
                _vision_header_user_payload(org),
                default=str,
            )
        }
    )
    return await _generate_json(
        system=resolve_system_prompt_text("vision.header_extract.system"),
        user_parts=parts,
        timeout_seconds=settings.runtime_llm_timeout_seconds,
    )


async def read_for_classification_gemini(
    file_path: str | Path,
    *,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    vision_page_images: list[bytes] | None = None,
) -> OcrArtifact:
    """Vision OCR only — headings/text excerpt, no document-type classification."""
    settings = get_settings()
    path = Path(file_path)
    images = resolve_pdf_page_images(path, vision_page_images)
    if not images:
        raise ValueError("gemini_no_pages")

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
        system=resolve_system_prompt_text("vision.gemini.read.system"),
        user_parts=parts,
        timeout_seconds=settings.runtime_llm_timeout_seconds,
    )
    if raw is None:
        raise ValueError("gemini_read_failed")

    excerpt = str(raw.get("text_excerpt") or raw.get("document_heading") or "").strip()[:12000]
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
    vision_page_images: list[bytes] | None = None,
) -> LlmDocumentResult | None:
    """Separate classify step with catalogue + few-shots (post-OCR)."""
    settings = get_settings()
    path = Path(file_path)
    images = resolve_pdf_page_images(path, vision_page_images)
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
        system=resolve_system_prompt_text("vision.gemini.classify.system", party_rules=party_llm_rules()),
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
    ocr: OcrArtifact,
    file_path: str | Path | None = None,
    *,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    confirmed_dt: str,
    few_shots: Sequence[dict[str, str]] | None = None,
    vision_page_images: list[bytes] | None = None,
) -> LlmDocumentResult | None:
    settings = get_settings()
    dt_token = confirmed_dt.strip().upper()
    selected_keys = _selected_keys_for_dt(document_types, dt_token)
    custom_keys = non_canonical_extraction_keys(selected_keys)
    system, user_text = build_structure_extract_prompts(
        ocr=ocr,
        org=org,
        document_types=document_types,
        confirmed_dt=dt_token,
        few_shots=few_shots,
        selected_keys=selected_keys,
        sparse=ocr.sparse,
    )

    parts: list[dict[str, Any]] = [{"text": user_text}]
    if ocr.sparse and file_path is not None:
        path = Path(file_path)
        images = resolve_pdf_page_images(path, vision_page_images)
        if images:
            parts = _image_parts(images) + parts

    raw = await _generate_json(
        system=system,
        user_parts=parts,
        timeout_seconds=settings.runtime_llm_timeout_seconds,
    )
    if raw is None:
        return None
    try:
        normalized = _normalize_llm_raw(
            raw,
            selected_keys=selected_keys,
            custom_keys=custom_keys,
        )
        normalized["suggested_dt"] = dt_token
        result = LlmDocumentResult.model_validate(normalized)
        result.raw = raw
        return result
    except Exception as exc:
        logger.warning("gemini_extract_invalid", error=str(exc))
        return None
