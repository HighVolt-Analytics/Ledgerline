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


def _is_retryable_openai_error(
    exc: Exception,
    *,
    retry_timeouts: bool,
) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError, httpx.RemoteProtocolError)):
        return True
    if not retry_timeouts:
        return False
    if isinstance(exc, (TimeoutError, httpx.TimeoutException, httpx.ReadTimeout)):
        return True
    message = str(exc).lower()
    return "timeout" in message or "timed out" in message


def _httpx_timeout(read_seconds: float) -> httpx.Timeout:
    return httpx.Timeout(connect=10.0, read=read_seconds, write=10.0, pool=10.0)


def _chat_json_once(
    *,
    timeout: float,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    from app.services.extraction.azure_openai_throttle import azure_openai_slot

    with azure_openai_slot():
        with httpx.Client(timeout=_httpx_timeout(timeout)) as client:
            response = client.post(
                _chat_url(),
                headers={
                    "api-key": get_settings().azure_openai_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            body = response.json()

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


def _retry_sleep_seconds(exc: Exception, attempt: int) -> float:
    """Backoff between retryable OpenAI errors; honour Retry-After on 429."""
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        headers = exc.response.headers
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
        if retry_after:
            try:
                return max(float(retry_after), 2.0)
            except ValueError:
                pass
        retry_ms = headers.get("retry-after-ms") or headers.get("Retry-After-Ms")
        if retry_ms:
            try:
                return max(float(retry_ms) / 1000.0, 2.0)
            except ValueError:
                pass
        # Azure TPM resets are often 10–60s; keep a firm floor so retries can succeed.
        return min(60.0, max(8.0, 4.0 * (2**attempt)))
    return 0.5 * (2**attempt)


def chat_json(
    *,
    system: str,
    user: str,
    timeout_seconds: int | None = None,
    require_runtime: bool = False,
) -> dict[str, Any] | None:
    from app.services.extraction.azure_openai_throttle import (
        azure_openai_cooldown_remaining_seconds,
        azure_openai_cooling_down,
        note_azure_openai_rate_limited,
        note_azure_openai_success,
    )

    settings = get_settings()
    if require_runtime:
        if not settings.runtime_llm_available:
            return None
    elif not is_azure_openai_enabled():
        return None

    if azure_openai_cooling_down("chat"):
        logger.info(
            "azure_openai_chat_skipped_circuit_open",
            remaining_seconds=round(azure_openai_cooldown_remaining_seconds("chat"), 1),
            require_runtime=require_runtime,
        )
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
    if require_runtime:
        timeout = timeout_seconds or settings.runtime_llm_timeout_seconds
        # Fail-fast on 429: at most 2 tries, then open circuit for rules/vision fallback.
        max_attempts = min(max(settings.runtime_llm_max_retries + 1, 1), 2)
        retry_timeouts = False
    else:
        timeout = timeout_seconds or settings.sample_proposal_llm_timeout_seconds
        max_attempts = 2
        retry_timeouts = True
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            result = _chat_json_once(timeout=timeout, payload=payload)
            if result is not None:
                note_azure_openai_success(scope="chat")
            return result
        except Exception as exc:
            last_error = exc
            is_429 = (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code == 429
            )
            if is_429:
                sleep_for = _retry_sleep_seconds(exc, attempt)
                note_azure_openai_rate_limited(sleep_for, scope="chat")
                # Do not burn minutes retrying a exhausted quota — fall back immediately.
                logger.warning(
                    "azure_openai_rate_limited_fail_fast",
                    attempt=attempt + 1,
                    cooldown_seconds=round(sleep_for, 1),
                    require_runtime=require_runtime,
                )
                return None
            if attempt < max_attempts - 1 and _is_retryable_openai_error(
                exc,
                retry_timeouts=retry_timeouts,
            ):
                import time

                sleep_for = _retry_sleep_seconds(exc, attempt)
                logger.info(
                    "azure_openai_chat_retry",
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    sleep_seconds=round(sleep_for, 2),
                    error=str(exc)[:200],
                )
                time.sleep(sleep_for)
                continue
            break
    if last_error is not None:
        logger.warning(
            "azure_openai_chat_failed",
            error=str(last_error),
            require_runtime=require_runtime,
            attempts=max_attempts,
        )
    return None


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
