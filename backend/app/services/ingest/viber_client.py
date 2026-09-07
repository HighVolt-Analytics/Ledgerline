"""Viber Public Account Bot API client."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)

VIBER_API_BASE = "https://chatapi.viber.com/pa"

_MESSAGE_EVENT_TYPES = [
    "delivered",
    "seen",
    "failed",
    "subscribed",
    "unsubscribed",
    "conversation_started",
    "message",
]

WELCOME_EVENT_TYPES = frozenset({"subscribed", "conversation_started"})


@dataclass
class ParsedViberMessage:
    message_token: str
    sender_id: str
    msg_type: str
    text: str | None
    media_url: str | None
    mime_type: str | None
    filename: str | None
    skip_ingest: bool = False


class ViberClient:
    def __init__(self, auth_token: str) -> None:
        self.auth_token = auth_token.strip()

    def _headers(self) -> dict[str, str]:
        return {
            "X-Viber-Auth-Token": self.auth_token,
            "Content-Type": "application/json",
        }

    def verify_signature(self, raw_body: bytes, signature_header: str | None) -> bool:
        if not self.auth_token or not signature_header:
            return False
        computed = hmac.new(
            self.auth_token.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(computed, signature_header.strip())

    async def set_webhook(self, url: str) -> dict[str, Any]:
        body = {
            "url": url,
            "event_types": _MESSAGE_EVENT_TYPES,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{VIBER_API_BASE}/set_webhook",
                headers=self._headers(),
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
            status = int(payload.get("status") or -1)
            if status != 0:
                raise RuntimeError(
                    f"Viber set_webhook failed: {payload.get('status_message') or payload}"
                )
            return payload

    async def get_account_info(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{VIBER_API_BASE}/get_account_info",
                headers=self._headers(),
                json={},
            )
            response.raise_for_status()
            payload = response.json()
            status = int(payload.get("status") or -1)
            if status != 0:
                raise RuntimeError(
                    f"Viber get_account_info failed: {payload.get('status_message') or payload}"
                )
            return payload

    async def send_message(self, receiver_id: str, text: str) -> dict[str, Any]:
        body = {
            "receiver": receiver_id,
            "type": "text",
            "text": text[:7000],
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{VIBER_API_BASE}/send_message",
                headers=self._headers(),
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
            status = int(payload.get("status") or -1)
            if status != 0:
                raise RuntimeError(
                    f"Viber send_message failed: {payload.get('status_message') or payload}"
                )
            return payload

    async def download_media(self, media_url: str) -> tuple[bytes, str]:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(
                media_url,
                headers={"X-Viber-Auth-Token": self.auth_token},
            )
            response.raise_for_status()
            mime_type = response.headers.get("content-type", "application/octet-stream")
            return response.content, mime_type


async def send_message_with_retry(
    client: ViberClient,
    *,
    receiver_id: str,
    text: str,
    attempts: int = 3,
) -> dict[str, Any] | None:
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return await client.send_message(receiver_id, text)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "viber_send_retry",
                attempt=attempt + 1,
                receiver_id=receiver_id,
                error=str(exc),
            )
            if attempt + 1 < attempts:
                await asyncio.sleep(0.5 * (attempt + 1))
    if last_exc:
        logger.error("viber_send_failed", receiver_id=receiver_id, error=str(last_exc))
    return None


def sender_id_from_event(payload: dict[str, Any]) -> str:
    """Viber user id from message (`sender`) or subscribe/welcome (`user`) payloads."""
    for key in ("sender", "user"):
        party = payload.get(key) or {}
        if isinstance(party, dict):
            sender_id = str(party.get("id") or "").strip()
            if sender_id:
                return sender_id
    return ""


def parse_viber_event(payload: dict[str, Any]) -> ParsedViberMessage | None:
    if payload.get("event") != "message":
        return None

    sender = payload.get("sender") or {}
    if not isinstance(sender, dict):
        return None
    sender_id = str(sender.get("id") or "").strip()
    if not sender_id:
        return None

    message = payload.get("message") or {}
    if not isinstance(message, dict):
        return None

    msg_type = str(message.get("type") or "").strip().lower()
    message_token = str(payload.get("message_token") or "")
    text = message.get("text")
    text_str = str(text).strip() if text is not None else None

    media_url: str | None = None
    filename: str | None = None
    mime_type: str | None = None

    if msg_type == "picture":
        media_url = str(message.get("media") or "") or None
        mime_type = "image/jpeg"
    elif msg_type == "file":
        media_url = str(message.get("media") or "") or None
        filename = str(message.get("file_name") or "") or None
        mime_type = str(message.get("media_type") or "") or None
    elif msg_type == "text":
        pass
    else:
        return ParsedViberMessage(
            message_token=message_token,
            sender_id=sender_id,
            msg_type=msg_type or "unknown",
            text=text_str,
            media_url=None,
            mime_type=None,
            filename=None,
            skip_ingest=True,
        )

    return ParsedViberMessage(
        message_token=message_token,
        sender_id=sender_id,
        msg_type=msg_type,
        text=text_str,
        media_url=media_url,
        mime_type=mime_type,
        filename=filename,
    )


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
