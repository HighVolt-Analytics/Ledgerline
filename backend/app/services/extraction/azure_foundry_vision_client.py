"""Azure AI Foundry GPT-4o Vision — OCR read, classify, and extract from document images."""

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
from app.services.extraction.llm_catalogue_rows import build_llm_catalogue_rows
from app.services.extraction.party_field_service import PARTY_LLM_RULES
from app.services.extraction.extraction_field_values import non_canonical_extraction_keys
from app.services.extraction.llm_document_service import (
    _normalize_llm_raw,
    _selected_keys_for_dt,
    build_structure_extract_prompts,
)
from app.services.tenant.tenant_org_context import OrgContext
from app.services.extraction.vision_pdf import pdf_page_images
from app.utils.logger import get_logger

logger = get_logger(__name__)

_CLASSIFY_SYSTEM = """You classify finance documents for accounts payable from document images.
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
- Examples with vendor_key match the sender/vendor — prefer those when the layout matches that supplier.
- Each catalogue row has recognition_mode signals or prompt.
- When recognition_mode is signals, treat recognition_rules as deterministic match hints for that code.
- When recognition_mode is prompt, treat llm_prompt as the authoritative description for that code."""

_FOUNDRY_READ_SYSTEM = """You read finance document images for accounts payable OCR.
Return JSON only with keys: document_heading, text_excerpt.
- document_heading is the primary visible document title or heading.
- text_excerpt is the full visible document text including tables, amounts, and labels (max 12000 chars)."""


def is_azure_foundry_vision_available() -> bool:
    return get_settings().azure_foundry_vision_available


def _chat_url() -> str:
    settings = get_settings()
    endpoint = settings.azure_ai_foundry_endpoint.rstrip("/")
    deployment = settings.azure_ai_foundry_deployment.strip() or "gpt-4o"
    version = settings.azure_ai_foundry_api_version.strip() or "2024-08-01-preview"
    return (
        f"{endpoint}/openai/deployments/{deployment}/chat/completions"
        f"?api-version={version}"
    )


def _catalogue_rows(document_types: Sequence[DocumentTypeDefinition]) -> list[dict[str, Any]]:
    return build_llm_catalogue_rows(document_types)


def _vision_content(user_text: str, images: list[bytes]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    for image in images:
        encoded = base64.b64encode(image).decode("ascii")
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}"},
            }
        )
    return parts


async def _vision_json(
    *,
    system: str,
    user_text: str,
    images: list[bytes],
    timeout_seconds: int,
) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.azure_foundry_vision_configured:
        return None

    payload: dict[str, Any] = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": _vision_content(user_text, images)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                _chat_url(),
                headers={
                    "api-key": settings.azure_ai_foundry_api_key.strip(),
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
    except Exception as exc:
        logger.warning("azure_foundry_vision_request_failed", error=str(exc))
        return None

    choices = body.get("choices") or []
    if not choices:
        return None
    content = (choices[0].get("message") or {}).get("content") or ""
    if not content.strip():
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("azure_foundry_vision_invalid_json")
        return None
    return parsed if isinstance(parsed, dict) else None


async def read_for_classification_azure_foundry(
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
        raise ValueError("azure_foundry_no_pages")

    system = _FOUNDRY_READ_SYSTEM

    user_text = json.dumps(
        {
            "tenant": {
                "legal_name": org.legal_name,
                "abn": org.abn,
            },
        },
        default=str,
    )

    raw = await _vision_json(
        system=system,
        user_text=user_text,
        images=images,
        timeout_seconds=settings.runtime_llm_timeout_seconds,
    )
    if raw is None:
        raise ValueError("azure_foundry_read_failed")

    excerpt = str(raw.get("text_excerpt") or raw.get("document_heading") or "").strip()[:12000]
    text_length = len(excerpt)
    sparse = text_length < settings.ocr_min_text_chars
    deployment = settings.azure_ai_foundry_deployment.strip() or "gpt-4o"
    return OcrArtifact(
        success=True,
        sparse=sparse,
        text=excerpt,
        text_length=text_length,
        di_model=deployment,
        layout_kv={},
        payload_json={
            "provider": "azure_foundry_vision",
            "document_heading": str(raw.get("document_heading") or "").strip(),
            "page_count": len(images),
        },
    )


async def classify_only_azure_foundry(
    file_path: str | Path,
    ocr: OcrArtifact,
    *,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    few_shots: Sequence[dict[str, str]] | None = None,
) -> LlmDocumentResult | None:
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

    raw = await _vision_json(
        system=_CLASSIFY_SYSTEM,
        user_text=user_text,
        images=images,
        timeout_seconds=settings.runtime_llm_timeout_seconds,
    )
    if raw is None:
        return None
    try:
        normalized = _normalize_llm_raw(raw)
        result = LlmDocumentResult.model_validate(normalized)
        result.raw = raw
        return result
    except Exception as exc:
        logger.warning("azure_foundry_classify_invalid", error=str(exc))
        return None


async def extract_fields_azure_foundry(
    ocr: OcrArtifact,
    file_path: str | Path | None = None,
    *,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    confirmed_dt: str,
    few_shots: Sequence[dict[str, str]] | None = None,
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

    images: list[bytes] = []
    if ocr.sparse and file_path is not None:
        path = Path(file_path)
        images = pdf_page_images(path)

    raw = await _vision_json(
        system=system,
        user_text=user_text,
        images=images,
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
        logger.warning("azure_foundry_extract_invalid", error=str(exc))
        return None
