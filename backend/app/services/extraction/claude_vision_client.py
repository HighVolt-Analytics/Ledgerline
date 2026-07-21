"""Claude on Azure AI Foundry — Anthropic Messages API for understood-path vision."""

from __future__ import annotations

import asyncio
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

# Azure Claude Sonnet (Foundry Messages API) rejects assistant prefill with 400:
# "This model does not support assistant message prefill."
_FENCE_OPEN_RE = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)
_FENCE_CLOSE_RE = re.compile(r"\s*```\s*$")


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
    """Parse a JSON object from model text (fences, prefill, trailing prose)."""
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = _FENCE_OPEN_RE.sub("", raw)
        raw = _FENCE_CLOSE_RE.sub("", raw).strip()
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    if start < 0:
        return None
    try:
        parsed, _ = json.JSONDecoder().raw_decode(raw[start:])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
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


def _response_text(body: dict[str, Any]) -> str:
    parts = body.get("content") or []
    text_chunks: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and part.get("text"):
            text_chunks.append(str(part["text"]))
    return "\n".join(text_chunks).strip()


async def _vision_json(
    *,
    system: str,
    user_text: str,
    images: list[bytes],
    timeout_seconds: int,
) -> dict[str, Any] | None:
    """Call Claude Messages API with Foundry-style 429 retry + JSON hardening."""
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
    if not settings.azure_claude_vision_configured:
        return None

    url = _messages_url()
    if not url:
        return None

    # Share the vision circuit with Foundry so batch reprocess backs off together.
    if azure_openai_cooling_down("vision"):
        remaining = azure_openai_cooldown_remaining_seconds("vision")
        wait_for = min(remaining, max(settings.azure_openai_cooldown_seconds, 15.0))
        if wait_for > 0:
            logger.info(
                "claude_vision_wait_circuit",
                remaining_seconds=round(remaining, 1),
                wait_seconds=round(wait_for, 1),
            )
            await asyncio.sleep(wait_for)

    deployment = settings.azure_ai_visualization_deployment.strip() or "claude-sonnet-4-6"
    anthropic_version = (
        settings.azure_ai_visualization_anthropic_version.strip() or "2023-06-01"
    )
    content: list[dict[str, Any]] = _image_content_blocks(images)
    content.append({"type": "text", "text": user_text})

    # No OpenAI response_format / no assistant prefill (Azure Claude rejects prefill).
    system_with_json = (
        f"{system.rstrip()}\n\n"
        "Return ONLY a single valid JSON object. "
        "No markdown fences, no commentary, no trailing text."
    )
    payload: dict[str, Any] = {
        "model": deployment,
        "max_tokens": 4096,
        "temperature": 0.0,
        "system": system_with_json,
        "messages": [
            {"role": "user", "content": content},
        ],
    }
    headers = {
        "content-type": "application/json",
        # Regional cognitive endpoints accept x-api-key; Foundry *.services.ai.azure.com
        # also documents api-key — send both for compatibility.
        "api-key": settings.azure_ai_visualization_api_key.strip(),
        "x-api-key": settings.azure_ai_visualization_api_key.strip(),
        "anthropic-version": anthropic_version,
    }

    # Survive 429 bursts the same way Foundry vision does.
    max_attempts = min(max(settings.runtime_llm_max_retries + 1, 3), 4)
    invalid_json_retries = 1

    for attempt in range(max_attempts):
        if attempt > 0 and azure_openai_cooling_down("vision"):
            remaining = azure_openai_cooldown_remaining_seconds("vision")
            wait_for = min(remaining, max(settings.azure_openai_cooldown_seconds, 15.0))
            if wait_for > 0:
                logger.info(
                    "claude_vision_wait_circuit_retry",
                    attempt=attempt + 1,
                    wait_seconds=round(wait_for, 1),
                )
                await asyncio.sleep(wait_for)
        try:
            async with azure_openai_slot_async():
                async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                    response = await client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    body = response.json()
        except Exception as exc:
            is_429 = (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code == 429
            )
            if is_429:
                sleep_for = _retry_sleep_seconds(exc, attempt)
                note_azure_openai_rate_limited(sleep_for, scope="vision")
                if attempt < max_attempts - 1:
                    logger.warning(
                        "claude_vision_rate_limited_retry",
                        attempt=attempt + 1,
                        max_attempts=max_attempts,
                        cooldown_seconds=round(sleep_for, 1),
                    )
                    await asyncio.sleep(sleep_for)
                    continue
                logger.warning(
                    "claude_vision_rate_limited_exhausted",
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
                    "claude_vision_retry",
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    sleep_seconds=round(sleep_for, 2),
                    error=str(exc)[:200],
                )
                await asyncio.sleep(sleep_for)
                continue
            detail = ""
            if isinstance(exc, httpx.HTTPStatusError):
                try:
                    detail = (exc.response.text or "")[:400]
                except Exception:
                    detail = ""
            logger.warning(
                "claude_vision_request_failed",
                error=str(exc),
                url=url,
                response_body=detail or None,
            )
            return None

        text = _response_text(body if isinstance(body, dict) else {})
        parsed = _parse_json_text(text)
        if parsed is not None:
            note_azure_openai_success(scope="vision")
            return parsed

        logger.warning(
            "claude_vision_invalid_json",
            attempt=attempt + 1,
            text_prefix=(text or "")[:240],
        )
        if invalid_json_retries > 0 and attempt < max_attempts - 1:
            invalid_json_retries -= 1
            # One repair retry: ask explicitly for JSON-only (still ends on user turn).
            payload = {
                **payload,
                "temperature": 0.0,
                "messages": [
                    {"role": "user", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "Your previous reply was not valid JSON. "
                            "Reply again with ONLY a JSON object, nothing else."
                        ),
                    },
                ],
            }
            await asyncio.sleep(0.5)
            continue
        return None

    return None


async def probe_understand_claude(images: list[bytes]) -> dict[str, Any] | None:
    """Lightweight yes/no understandability check — not classify/extract."""
    settings = get_settings()
    if not images:
        return None
    user_text = json.dumps(
        {
            "task": "vision_understand",
            "instruction": (
                "Decide whether you can clearly read this AP/trade document "
                "(invoice, packing list, GRN, Proof of Delivery, AWB/BOL, permit, "
                "or similar) well enough for later header extract. "
                "Do not require invoice amounts or line items. "
                "Say no only for blank, extreme blur, or non-document junk."
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
