"""Claude on Azure AI Foundry — Anthropic Messages API for understood-path vision."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Sequence

import httpx

from app.config import get_settings
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.extraction_field_values import non_canonical_extraction_keys
from app.services.extraction.llm_catalogue_rows import build_llm_catalogue_rows
from app.services.extraction.llm_document_service import (
    _normalize_llm_raw,
    _selected_keys_for_dt,
    build_structure_extract_prompts,
)
from app.services.extraction.party_field_service import party_llm_rules
from app.services.extraction.vision_pdf import resolve_pdf_page_images
from app.services.prompt_registry import resolve_system_prompt_text
from app.services.tenant.tenant_org_context import OrgContext
from app.utils.logger import get_logger

logger = get_logger(__name__)

_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)


def is_claude_vision_available() -> bool:
    return get_settings().claude_vision_available


def _catalogue_rows(document_types: Sequence[DocumentTypeDefinition]) -> list[dict[str, Any]]:
    return build_llm_catalogue_rows(document_types)


def _messages_url() -> str:
    endpoint = get_settings().azure_ai_visualization_endpoint.strip().rstrip("/")
    if not endpoint:
        return ""
    if endpoint.endswith("/v1/messages"):
        return endpoint
    if endpoint.endswith("/anthropic"):
        return f"{endpoint}/v1/messages"
    return f"{endpoint}/anthropic/v1/messages"


def _parse_json_text(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = _JSON_FENCE_RE.search(raw)
    if match:
        try:
            parsed = json.loads(match.group(1))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _image_content_blocks(images: list[bytes]) -> list[dict[str, Any]]:
    from app.services.extraction.vision_pdf import sniff_image_media_type

    blocks: list[dict[str, Any]] = []
    for image in images:
        media = sniff_image_media_type(image)
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media,
                    "data": base64.b64encode(image).decode("ascii"),
                },
            }
        )
    return blocks


async def _vision_json(
    *,
    system: str,
    user_text: str,
    images: list[bytes],
    timeout_seconds: int,
) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.azure_claude_vision_configured:
        return None

    url = _messages_url()
    if not url:
        return None

    deployment = settings.azure_ai_visualization_deployment.strip() or "claude-sonnet-4-6"
    anthropic_version = (
        settings.azure_ai_visualization_anthropic_version.strip() or "2023-06-01"
    )
    content: list[dict[str, Any]] = _image_content_blocks(images)
    content.append({"type": "text", "text": user_text})

    # Claude does not use OpenAI response_format; require JSON in the system prompt.
    system_with_json = (
        f"{system.rstrip()}\n\n"
        "Return ONLY a valid JSON object. No markdown fences, no commentary."
    )
    payload: dict[str, Any] = {
        "model": deployment,
        "max_tokens": 4096,
        "temperature": 0.1,
        "system": system_with_json,
        "messages": [{"role": "user", "content": content}],
    }
    headers = {
        "content-type": "application/json",
        # Regional cognitive endpoints accept x-api-key; Foundry *.services.ai.azure.com
        # also documents api-key — send both for compatibility.
        "api-key": settings.azure_ai_visualization_api_key.strip(),
        "x-api-key": settings.azure_ai_visualization_api_key.strip(),
        "anthropic-version": anthropic_version,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
    except Exception as exc:
        logger.warning("claude_vision_request_failed", error=str(exc), url=url)
        return None

    parts = body.get("content") or []
    text_chunks: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and part.get("text"):
            text_chunks.append(str(part["text"]))
    text = "\n".join(text_chunks).strip()
    parsed = _parse_json_text(text)
    if parsed is None:
        logger.warning("claude_vision_invalid_json")
    return parsed


async def probe_understand_claude(images: list[bytes]) -> dict[str, Any] | None:
    """Lightweight yes/no understandability check — not classify/extract."""
    settings = get_settings()
    if not images:
        return None
    user_text = json.dumps(
        {
            "task": "vision_understand",
            "instruction": (
                "Decide whether you can clearly read and understand this "
                "finance document well enough to extract key fields later."
            ),
        }
    )
    return await _vision_json(
        system=resolve_system_prompt_text("vision.understand.system"),
        user_text=user_text,
        images=images,
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


async def extract_header_claude(
    images: list[bytes],
    *,
    org: OrgContext,
) -> dict[str, Any] | None:
    """Header identity extract: printed title, counterparty, linking refs."""
    settings = get_settings()
    if not images:
        return None
    user_text = json.dumps(
        _vision_header_user_payload(org),
        default=str,
    )
    return await _vision_json(
        system=resolve_system_prompt_text("vision.header_extract.system"),
        user_text=user_text,
        images=images,
        timeout_seconds=settings.runtime_llm_timeout_seconds,
    )


async def read_for_classification_claude(
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
        raise ValueError("claude_no_pages")

    system = resolve_system_prompt_text("vision.foundry.read.system")
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
        raise ValueError("claude_read_failed")

    excerpt = str(raw.get("text_excerpt") or raw.get("document_heading") or "").strip()[:12000]
    text_length = len(excerpt)
    sparse = text_length < settings.ocr_min_text_chars
    deployment = settings.azure_ai_visualization_deployment.strip() or "claude-sonnet-4-6"
    return OcrArtifact(
        success=True,
        sparse=sparse,
        text=excerpt,
        text_length=text_length,
        di_model=deployment,
        layout_kv={},
        payload_json={
            "provider": "claude_vision",
            "document_heading": str(raw.get("document_heading") or "").strip(),
            "page_count": len(images),
        },
    )


async def classify_only_claude(
    file_path: str | Path,
    ocr: OcrArtifact,
    *,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    few_shots: Sequence[dict[str, str]] | None = None,
    vision_page_images: list[bytes] | None = None,
) -> LlmDocumentResult | None:
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
    raw = await _vision_json(
        system=resolve_system_prompt_text(
            "vision.foundry.classify.system",
            party_rules=party_llm_rules(),
        ),
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
        logger.warning("claude_classify_invalid", error=str(exc))
        return None


async def extract_fields_claude(
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

    images: list[bytes] = []
    if ocr.sparse and file_path is not None:
        path = Path(file_path)
        images = resolve_pdf_page_images(path, vision_page_images)

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
        logger.warning("claude_extract_invalid", error=str(exc))
        return None
