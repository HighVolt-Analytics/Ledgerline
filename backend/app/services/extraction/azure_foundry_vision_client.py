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
from app.services.extraction.party_field_service import party_llm_rules
from app.services.extraction.extraction_field_values import non_canonical_extraction_keys
from app.services.extraction.llm_document_service import (
    _normalize_llm_raw,
    _selected_keys_for_dt,
    build_structure_extract_prompts,
)
from app.services.prompt_registry import resolve_system_prompt_text
from app.services.tenant.tenant_org_context import OrgContext
from app.services.extraction.vision_pdf import resolve_pdf_page_images
from app.utils.logger import get_logger

logger = get_logger(__name__)


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
    from app.services.extraction.vision_pdf import sniff_image_media_type

    parts: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    for image in images:
        encoded = base64.b64encode(image).decode("ascii")
        media = sniff_image_media_type(image)
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{media};base64,{encoded}"},
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
    import asyncio

    from app.services.extraction.azure_openai_client import (
        _is_retryable_openai_error,
        _retry_sleep_seconds,
    )
    from app.services.extraction.azure_openai_throttle import (
        azure_openai_cooldown_remaining_seconds,
        azure_openai_cooling_down,
        azure_openai_slot_async,
        note_azure_openai_rate_limited,
        note_azure_openai_success,
    )

    settings = get_settings()
    if not settings.azure_foundry_vision_configured:
        return None

    if azure_openai_cooling_down("vision"):
        logger.info(
            "azure_foundry_vision_skipped_circuit_open",
            remaining_seconds=round(azure_openai_cooldown_remaining_seconds("vision"), 1),
        )
        return None

    payload: dict[str, Any] = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": _vision_content(user_text, images)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }
    max_attempts = min(max(settings.runtime_llm_max_retries + 1, 2), 3)
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            async with azure_openai_slot_async():
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
            last_error = exc
            is_429 = (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code == 429
            )
            if is_429:
                sleep_for = _retry_sleep_seconds(exc, attempt)
                note_azure_openai_rate_limited(sleep_for, scope="vision")
                logger.warning(
                    "azure_foundry_vision_rate_limited_fail_fast",
                    attempt=attempt + 1,
                    cooldown_seconds=round(sleep_for, 1),
                )
                return None
            if attempt < max_attempts - 1 and _is_retryable_openai_error(
                exc,
                retry_timeouts=False,
            ):
                sleep_for = _retry_sleep_seconds(exc, attempt)
                logger.info(
                    "azure_foundry_vision_retry",
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    sleep_seconds=round(sleep_for, 2),
                    error=str(exc)[:200],
                )
                await asyncio.sleep(sleep_for)
                continue
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
        if isinstance(parsed, dict):
            note_azure_openai_success(scope="vision")
            return parsed
        return None

    if last_error is not None:
        logger.warning("azure_foundry_vision_request_failed", error=str(last_error))
    return None


async def probe_understand_azure_foundry(images: list[bytes]) -> dict[str, Any] | None:
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


async def extract_header_azure_foundry(
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


async def read_for_classification_azure_foundry(
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
        raise ValueError("azure_foundry_no_pages")

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
        logger.warning("azure_foundry_extract_invalid", error=str(exc))
        return None
