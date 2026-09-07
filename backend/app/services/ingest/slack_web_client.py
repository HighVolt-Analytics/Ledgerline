"""Slack Web API + Events API client (OAuth, files, messages, signature verify)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.services.shared.public_api_url import slack_oauth_callback_url
from app.utils.logger import get_logger

logger = get_logger(__name__)

SLACK_API_BASE = "https://slack.com/api"
SLACK_OAUTH_AUTHORIZE = "https://slack.com/oauth/v2/authorize"
SIGNATURE_MAX_AGE_SECONDS = 60 * 5


@dataclass
class SlackFileRef:
    file_id: str
    name: str | None = None
    mimetype: str | None = None
    url_private: str | None = None
    size: int | None = None


@dataclass
class ParsedSlackMessage:
    event_id: str
    team_id: str
    channel: str
    user_id: str
    text: str | None
    ts: str
    thread_ts: str | None
    files: list[SlackFileRef] = field(default_factory=list)
    event_type: str = "message"
    skip_ai: bool = False


@dataclass
class ParsedSlackLifecycle:
    event_id: str
    team_id: str
    event_type: str  # app_uninstalled | tokens_revoked


def verify_slack_signature(
    raw_body: bytes,
    timestamp: str | None,
    signature_header: str | None,
    *,
    now: int | None = None,
) -> bool:
    """Verify X-Slack-Signature (v0 HMAC-SHA256) with 5-minute replay window."""
    secret = get_settings().slack_signing_secret.strip()
    if not secret or not timestamp or not signature_header:
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    current = now if now is not None else int(time.time())
    if abs(current - ts) > SIGNATURE_MAX_AGE_SECONDS:
        return False
    if not signature_header.startswith("v0="):
        return False
    basestring = b"v0:" + timestamp.encode("utf-8") + b":" + raw_body
    computed = (
        "v0="
        + hmac.new(
            secret.encode("utf-8"),
            basestring,
            hashlib.sha256,
        ).hexdigest()
    )
    return hmac.compare_digest(computed, signature_header)


def build_oauth_authorize_url(*, state: str) -> str:
    settings = get_settings()
    redirect_uri = slack_oauth_callback_url()
    params = {
        "client_id": settings.slack_client_id.strip(),
        "scope": settings.slack_oauth_bot_scopes.replace(" ", ""),
        "redirect_uri": redirect_uri,
        "state": state,
    }
    logger.info("slack_oauth_authorize", redirect_uri=redirect_uri)
    return f"{SLACK_OAUTH_AUTHORIZE}?{urlencode(params)}"


async def exchange_code_for_token(code: str) -> dict[str, Any]:
    settings = get_settings()
    redirect_uri = slack_oauth_callback_url()
    data = {
        "client_id": settings.slack_client_id.strip(),
        "client_secret": settings.slack_client_secret.strip(),
        "code": code,
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{SLACK_API_BASE}/oauth.v2.access",
            data=data,
        )
        if response.is_error:
            logger.error(
                "slack_oauth_exchange_http_error",
                status=response.status_code,
                body=response.text[:500],
            )
            response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            logger.error(
                "slack_oauth_exchange_failed",
                error=payload.get("error"),
                body=str(payload)[:500],
            )
            raise RuntimeError(str(payload.get("error") or "oauth_failed"))
        return payload


async def _slack_api(
    method: str,
    *,
    access_token: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        if json_body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
            response = await client.post(
                f"{SLACK_API_BASE}/{method}",
                headers=headers,
                json=json_body,
            )
        else:
            response = await client.get(
                f"{SLACK_API_BASE}/{method}",
                headers=headers,
                params=params or {},
            )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            err = str(payload.get("error") or "unknown_error")
            raise RuntimeError(f"slack_api_{method}_failed:{err}")
        return payload


async def _with_retry(coro_factory, *, attempts: int = 3, label: str = "slack_api"):
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return await coro_factory()
        except Exception as exc:
            last_exc = exc
            if attempt + 1 < attempts:
                await asyncio.sleep(0.5 * (attempt + 1))
    logger.warning(
        f"{label}_retry_exhausted",
        error=str(last_exc) if last_exc else "",
    )
    raise last_exc if last_exc else RuntimeError(f"{label}_failed")


async def users_info(access_token: str, user_id: str) -> dict[str, Any]:
    async def _call():
        return await _slack_api(
            "users.info",
            access_token=access_token,
            params={"user": user_id},
        )

    return await _with_retry(_call, label="slack_users_info")


async def files_info(access_token: str, file_id: str) -> dict[str, Any]:
    async def _call():
        return await _slack_api(
            "files.info",
            access_token=access_token,
            params={"file": file_id},
        )

    return await _with_retry(_call, label="slack_files_info")


async def download_private_file(
    url_private: str,
    *,
    access_token: str,
) -> bytes:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(url_private, headers=headers)
        response.raise_for_status()
        return response.content


async def auth_test(access_token: str) -> dict[str, Any]:
    return await _slack_api("auth.test", access_token=access_token, json_body={})


async def send_message(
    access_token: str,
    *,
    channel: str,
    text: str,
    thread_ts: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "channel": channel,
        "text": text[:4000],
    }
    if thread_ts:
        body["thread_ts"] = thread_ts

    async def _call():
        return await _slack_api(
            "chat.postMessage",
            access_token=access_token,
            json_body=body,
        )

    return await _with_retry(_call, label="slack_send_message")


async def send_message_with_retry(
    access_token: str,
    *,
    channel: str,
    text: str,
    thread_ts: str | None = None,
    attempts: int = 3,
) -> dict[str, Any] | None:
    try:
        return await send_message(
            access_token,
            channel=channel,
            text=text,
            thread_ts=thread_ts,
        )
    except Exception as exc:
        logger.warning("slack_send_message_failed", error=str(exc), attempts=attempts)
        return None


def _file_from_payload(raw: dict[str, Any]) -> SlackFileRef | None:
    file_id = str(raw.get("id") or "").strip()
    if not file_id:
        return None
    size_raw = raw.get("size")
    size: int | None
    try:
        size = int(size_raw) if size_raw is not None else None
    except (TypeError, ValueError):
        size = None
    return SlackFileRef(
        file_id=file_id,
        name=str(raw.get("name") or "") or None,
        mimetype=str(raw.get("mimetype") or "") or None,
        url_private=str(raw.get("url_private") or raw.get("url_private_download") or "")
        or None,
        size=size,
    )


def parse_slack_payload(
    payload: dict[str, Any],
) -> tuple[list[ParsedSlackMessage], list[ParsedSlackLifecycle]]:
    """Extract ingestible messages and lifecycle events from an Events API payload."""
    if payload.get("type") != "event_callback":
        return [], []

    event_id = str(payload.get("event_id") or "").strip()
    team_id = str(payload.get("team_id") or "").strip()
    event = payload.get("event")
    if not isinstance(event, dict) or not event_id:
        return [], []

    event_type = str(event.get("type") or "").strip()
    if not team_id:
        team_id = str(event.get("team") or "").strip()

    if event_type in {"app_uninstalled", "tokens_revoked"}:
        if not team_id:
            return [], []
        return [], [
            ParsedSlackLifecycle(
                event_id=event_id,
                team_id=team_id,
                event_type=event_type,
            )
        ]

    # Skip bot-authored events to avoid reply loops
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return [], []

    subtype = str(event.get("subtype") or "").strip()
    skip_subtypes = {
        "message_changed",
        "message_deleted",
        "channel_join",
        "channel_leave",
        "channel_topic",
        "channel_purpose",
        "channel_name",
        "channel_archive",
        "channel_unarchive",
        "group_join",
        "group_leave",
    }
    if subtype in skip_subtypes:
        return [], []

    if event_type not in {"message", "app_mention"}:
        return [], []

    user_id = str(event.get("user") or "").strip()
    channel = str(event.get("channel") or "").strip()
    ts = str(event.get("ts") or "").strip()
    if not user_id or not channel or not team_id:
        return [], []

    files: list[SlackFileRef] = []
    for raw_file in event.get("files") or []:
        if isinstance(raw_file, dict):
            ref = _file_from_payload(raw_file)
            if ref:
                files.append(ref)

    text = str(event.get("text") or "") or None
    thread_ts = str(event.get("thread_ts") or "") or None
    # Prefer threading under the original message ts
    reply_thread = thread_ts or ts

    skip_ai = False
    if subtype and subtype not in {"file_share", "file_mention"}:
        # Unknown subtypes with no files — skip
        if not files:
            skip_ai = True

    return [
        ParsedSlackMessage(
            event_id=event_id,
            team_id=team_id,
            channel=channel,
            user_id=user_id,
            text=text,
            ts=ts,
            thread_ts=reply_thread,
            files=files,
            event_type=event_type,
            skip_ai=skip_ai,
        )
    ], []


def extension_for_mime(mime_type: str, filename: str | None = None) -> str:
    if filename and "." in filename:
        return filename.rsplit(".", 1)[-1].lower()
    mime = mime_type.split(";")[0].strip().lower()
    mapping = {
        "application/pdf": "pdf",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }
    return mapping.get(mime, "bin")
