"""Thin Azure OpenAI client for sample proposal wizard."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def is_azure_openai_configured() -> bool:
    return get_settings().azure_openai_configured


def is_azure_openai_enabled() -> bool:
    return get_settings().azure_openai_enabled


def _api_version() -> str:
    return get_settings().azure_openai_api_version.strip() or "2024-02-15-preview"


def _chat_url() -> str:
    settings = get_settings()
    endpoint = settings.azure_openai_endpoint.rstrip("/")
    deployment = settings.azure_openai_chat_deployment
    return (
        f"{endpoint}/openai/deployments/{deployment}/chat/completions"
        f"?api-version={_api_version()}"
    )


def _embedding_url() -> str:
    settings = get_settings()
    endpoint = settings.azure_openai_endpoint.rstrip("/")
    deployment = settings.azure_openai_embedding_deployment.strip()
    return (
        f"{endpoint}/openai/deployments/{deployment}/embeddings"
        f"?api-version={_api_version()}"
    )


def chat_json(
    *,
    system: str,
    user: str,
    timeout_seconds: int | None = None,
    require_runtime: bool = False,
) -> dict[str, Any] | None:
    settings = get_settings()
    if require_runtime:
        if not settings.runtime_llm_available:
            return None
    elif not is_azure_openai_enabled():
        return None
    payload: dict[str, Any] = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    deployment = settings.azure_openai_chat_deployment.lower()
    if "gpt-5" not in deployment:
        payload["temperature"] = 0.1
    timeout = timeout_seconds or settings.sample_proposal_llm_timeout_seconds
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                _chat_url(),
                headers={
                    "api-key": settings.azure_openai_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
    except Exception as exc:
        logger.warning("azure_openai_chat_failed", error=str(exc))
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
        logger.warning("azure_openai_chat_invalid_json")
        return None
    return parsed if isinstance(parsed, dict) else None


async def chat_json_async(
    *,
    system: str,
    user: str,
    timeout_seconds: int | None = None,
    require_runtime: bool = False,
) -> dict[str, Any] | None:
    """Non-blocking wrapper for use inside async request handlers and pipeline."""
    return await asyncio.to_thread(
        chat_json,
        system=system,
        user=user,
        timeout_seconds=timeout_seconds,
        require_runtime=require_runtime,
    )


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    if not is_azure_openai_configured():
        return None
    cleaned = [text.strip() for text in texts if text and text.strip()]
    if not cleaned:
        return []
    settings = get_settings()
    payload = {"input": cleaned}
    try:
        with httpx.Client(timeout=settings.sample_proposal_llm_timeout_seconds) as client:
            response = client.post(
                _embedding_url(),
                headers={
                    "api-key": settings.azure_openai_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
    except Exception as exc:
        logger.warning("azure_openai_embed_failed", error=str(exc))
        return None

    rows = body.get("data") or []
    vectors: list[list[float]] = []
    for row in sorted(rows, key=lambda item: int(item.get("index", 0))):
        embedding = row.get("embedding")
        if isinstance(embedding, list):
            vectors.append([float(v) for v in embedding])
    return vectors if len(vectors) == len(cleaned) else None
