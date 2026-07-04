"""Meta Graph API client for WhatsApp Business Cloud API."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.services.shared.public_api_url import webhook_meta_url, whatsapp_oauth_callback_url
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class WhatsappPhoneNumber:
    phone_number_id: str
    display_phone_number: str
    verified_name: str
    waba_id: str


@dataclass
class ParsedWhatsappMessage:
    message_id: str
    sender_wa_id: str
    phone_number_id: str
    waba_id: str
    msg_type: str
    text: str | None
    media_id: str | None
    mime_type: str | None
    filename: str | None
    caption: str | None
    skip_ai: bool = False


def graph_base() -> str:
    version = get_settings().whatsapp_graph_api_version.strip() or "v21.0"
    return f"https://graph.facebook.com/{version}"


def app_access_token() -> str:
    settings = get_settings()
    return f"{settings.whatsapp_effective_app_id}|{settings.whatsapp_effective_app_secret}"


def verify_webhook_signature(raw_body: bytes, signature_header: str | None) -> bool:
    secret = get_settings().whatsapp_effective_app_secret
    if not secret or not signature_header:
        return False
    expected_prefix = "sha256="
    if not signature_header.startswith(expected_prefix):
        return False
    received = signature_header[len(expected_prefix) :]
    computed = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(received, computed)


def build_oauth_authorize_url(*, state: str) -> str:
    settings = get_settings()
    redirect_uri = whatsapp_oauth_callback_url()
    params = {
        "client_id": settings.whatsapp_effective_app_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": settings.whatsapp_oauth_scopes.replace(",", ","),
        "response_type": "code",
    }
    logger.info("whatsapp_oauth_authorize", redirect_uri=redirect_uri)
    return f"https://www.facebook.com/{settings.whatsapp_graph_api_version}/dialog/oauth?{urlencode(params)}"


async def exchange_code_for_token(code: str) -> dict[str, Any]:
    settings = get_settings()
    redirect_uri = whatsapp_oauth_callback_url()
    params = {
        "client_id": settings.whatsapp_effective_app_id,
        "client_secret": settings.whatsapp_effective_app_secret,
        "redirect_uri": redirect_uri,
        "code": code,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{graph_base()}/oauth/access_token", params=params)
        if response.is_error:
            logger.error(
                "whatsapp_oauth_exchange_failed",
                redirect_uri=redirect_uri,
                body=response.text[:500],
            )
            response.raise_for_status()
        return response.json()


async def exchange_long_lived_token(short_lived_token: str) -> dict[str, Any]:
    settings = get_settings()
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": settings.whatsapp_effective_app_id,
        "client_secret": settings.whatsapp_effective_app_secret,
        "fb_exchange_token": short_lived_token,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{graph_base()}/oauth/access_token", params=params)
        response.raise_for_status()
        return response.json()


async def debug_token(input_token: str) -> dict[str, Any]:
    params = {
        "input_token": input_token,
        "access_token": app_access_token(),
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{graph_base()}/debug_token", params=params)
        response.raise_for_status()
        return response.json()


async def discover_waba_ids(user_token: str) -> list[str]:
    """Return WhatsApp Business Account ids accessible to the user token."""
    waba_ids: list[str] = []

    debug = await debug_token(user_token)
    data = debug.get("data") if isinstance(debug, dict) else {}
    granular = data.get("granular_scopes") if isinstance(data, dict) else []
    if isinstance(granular, list):
        for scope in granular:
            if not isinstance(scope, dict):
                continue
            if scope.get("scope") in {
                "whatsapp_business_management",
                "whatsapp_business_messaging",
            }:
                target_ids = scope.get("target_ids") or []
                if isinstance(target_ids, list):
                    for tid in target_ids:
                        text = str(tid).strip()
                        if text and text not in waba_ids:
                            waba_ids.append(text)

    headers = {"Authorization": f"Bearer {user_token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{graph_base()}/me/businesses",
            headers=headers,
            params={
                "fields": (
                    "id,name,"
                    "owned_whatsapp_business_accounts{id,name,"
                    "phone_numbers{id,display_phone_number,verified_name}}"
                ),
            },
        )
        if response.is_error:
            logger.warning("whatsapp_businesses_list_failed", body=response.text[:300])
        else:
            for biz in response.json().get("data") or []:
                if not isinstance(biz, dict):
                    continue
                waba_block = biz.get("owned_whatsapp_business_accounts") or {}
                for waba in waba_block.get("data") or []:
                    if not isinstance(waba, dict):
                        continue
                    wid = str(waba.get("id") or "").strip()
                    if wid and wid not in waba_ids:
                        waba_ids.append(wid)

        if waba_ids:
            return waba_ids

        # Legacy fallback: per-business owned WABA edge
        response = await client.get(
            f"{graph_base()}/me/businesses",
            headers=headers,
            params={"fields": "id,name"},
        )
        if response.is_error:
            return waba_ids
        businesses = response.json().get("data") or []
        for biz in businesses:
            if not isinstance(biz, dict):
                continue
            biz_id = str(biz.get("id") or "").strip()
            if not biz_id:
                continue
            owned = await client.get(
                f"{graph_base()}/{biz_id}/owned_whatsapp_business_accounts",
                headers=headers,
                params={"fields": "id,name"},
            )
            if owned.is_error:
                logger.debug(
                    "whatsapp_owned_waba_failed",
                    business_id=biz_id,
                    body=owned.text[:200],
                )
                continue
            for row in owned.json().get("data") or []:
                if isinstance(row, dict):
                    wid = str(row.get("id") or "").strip()
                    if wid and wid not in waba_ids:
                        waba_ids.append(wid)
    return waba_ids


def _phones_from_businesses_payload(payload: dict[str, Any]) -> list[WhatsappPhoneNumber]:
    phones: list[WhatsappPhoneNumber] = []
    for biz in payload.get("data") or []:
        if not isinstance(biz, dict):
            continue
        waba_block = biz.get("owned_whatsapp_business_accounts") or {}
        for waba in waba_block.get("data") or []:
            if not isinstance(waba, dict):
                continue
            waba_id = str(waba.get("id") or "").strip()
            if not waba_id:
                continue
            pn_block = waba.get("phone_numbers") or {}
            for row in pn_block.get("data") or []:
                if not isinstance(row, dict):
                    continue
                phone_id = str(row.get("id") or "").strip()
                if not phone_id:
                    continue
                phones.append(
                    WhatsappPhoneNumber(
                        phone_number_id=phone_id,
                        display_phone_number=str(row.get("display_phone_number") or ""),
                        verified_name=str(row.get("verified_name") or waba.get("name") or ""),
                        waba_id=waba_id,
                    )
                )
    return phones


async def discover_whatsapp_phones(user_token: str) -> list[WhatsappPhoneNumber]:
    """Discover WABA phone numbers via nested business graph query + fallbacks."""
    headers = {"Authorization": f"Bearer {user_token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{graph_base()}/me/businesses",
            headers=headers,
            params={
                "fields": (
                    "id,name,"
                    "owned_whatsapp_business_accounts{id,name,"
                    "phone_numbers{id,display_phone_number,verified_name}}"
                ),
            },
        )
        if not response.is_error:
            phones = _phones_from_businesses_payload(response.json())
            if phones:
                logger.info("whatsapp_discovered_phones", count=len(phones), source="businesses_nested")
                return phones
            logger.warning(
                "whatsapp_businesses_nested_empty",
                body=response.text[:400],
            )
        else:
            logger.warning(
                "whatsapp_businesses_nested_failed",
                body=response.text[:400],
            )

    waba_ids = await discover_waba_ids(user_token)
    logger.info("whatsapp_discovered_wabas", count=len(waba_ids), waba_ids=waba_ids[:5])
    phones: list[WhatsappPhoneNumber] = []
    for waba_id in waba_ids:
        found = await list_phone_numbers(waba_id, access_token=user_token)
        phones.extend(found)
    if phones:
        logger.info("whatsapp_discovered_phones", count=len(phones), source="waba_phone_numbers")
    return phones


async def list_phone_numbers(
    waba_id: str,
    *,
    access_token: str,
) -> list[WhatsappPhoneNumber]:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{graph_base()}/{waba_id}/phone_numbers",
            headers=headers,
            params={
                "fields": "id,display_phone_number,verified_name,status,platform_type",
            },
        )
        if response.is_error:
            logger.warning(
                "whatsapp_phone_numbers_failed",
                waba_id=waba_id,
                body=response.text[:500],
            )
            return []
        rows = response.json().get("data") or []

    out: list[WhatsappPhoneNumber] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        phone_id = str(row.get("id") or "").strip()
        if not phone_id:
            continue
        out.append(
            WhatsappPhoneNumber(
                phone_number_id=phone_id,
                display_phone_number=str(row.get("display_phone_number") or ""),
                verified_name=str(row.get("verified_name") or ""),
                waba_id=waba_id,
            )
        )
    return out


async def subscribe_waba_webhooks(waba_id: str, *, access_token: str) -> None:
    settings = get_settings()
    callback = webhook_meta_url()
    payload = {
        "override_callback_uri": callback,
        "verify_token": settings.whatsapp_effective_verify_token,
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{graph_base()}/{waba_id}/subscribed_apps",
            headers=headers,
            json=payload,
        )
        if response.is_error:
            logger.error(
                "whatsapp_waba_subscribe_failed",
                waba_id=waba_id,
                body=response.text[:500],
            )
            response.raise_for_status()
    logger.info("whatsapp_waba_subscribed", waba_id=waba_id, callback=callback)


async def get_phone_profile(
    phone_number_id: str,
    *,
    access_token: str,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{graph_base()}/{phone_number_id}",
            headers=headers,
            params={
                "fields": (
                    "id,display_phone_number,verified_name,status,platform_type,"
                    "quality_rating,messaging_limit_tier"
                ),
            },
        )
        response.raise_for_status()
        return response.json()


async def download_media(media_id: str, *, access_token: str) -> tuple[bytes, str]:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        meta_response = await client.get(
            f"{graph_base()}/{media_id}",
            headers=headers,
        )
        meta_response.raise_for_status()
        meta = meta_response.json()
        url = str(meta.get("url") or "")
        mime_type = str(meta.get("mime_type") or "application/octet-stream")
        if not url:
            raise RuntimeError("Media metadata missing download url")
        file_response = await client.get(url, headers=headers)
        file_response.raise_for_status()
        return file_response.content, mime_type


async def send_text_message(
    phone_number_id: str,
    *,
    access_token: str,
    to_wa_id: str,
    text: str,
) -> dict[str, Any]:
    body = {
        "messaging_product": "whatsapp",
        "to": to_wa_id,
        "type": "text",
        "text": {"body": text[:4000]},
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{graph_base()}/{phone_number_id}/messages",
            headers=headers,
            json=body,
        )
        if response.is_error:
            logger.error(
                "whatsapp_send_failed",
                phone_number_id=phone_number_id,
                body=response.text[:500],
            )
            response.raise_for_status()
        return response.json()


async def send_text_message_with_retry(
    phone_number_id: str,
    *,
    access_token: str,
    to_wa_id: str,
    text: str,
    attempts: int = 3,
) -> dict[str, Any] | None:
    import asyncio

    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return await send_text_message(
                phone_number_id,
                access_token=access_token,
                to_wa_id=to_wa_id,
                text=text,
            )
        except Exception as exc:
            last_exc = exc
            if attempt + 1 < attempts:
                await asyncio.sleep(0.5 * (attempt + 1))
    logger.warning(
        "whatsapp_send_retry_exhausted",
        phone_number_id=phone_number_id,
        error=str(last_exc) if last_exc else "",
    )
    return None


async def mark_message_read(
    phone_number_id: str,
    *,
    access_token: str,
    message_id: str,
) -> None:
    body = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"{graph_base()}/{phone_number_id}/messages",
            headers=headers,
            json=body,
        )
        if response.is_error:
            logger.debug("whatsapp_mark_read_failed", body=response.text[:200])


def parse_whatsapp_messages(payload: dict[str, Any]) -> list[ParsedWhatsappMessage]:
    """Extract inbound messages from a whatsapp_business_account webhook payload."""
    if payload.get("object") != "whatsapp_business_account":
        return []

    parsed: list[ParsedWhatsappMessage] = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        waba_id = str(entry.get("id") or "")
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            if change.get("field") != "messages":
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata") or {}
            phone_number_id = str(metadata.get("phone_number_id") or "")

            for msg in value.get("messages") or []:
                if not isinstance(msg, dict):
                    continue
                msg_type = str(msg.get("type") or "")
                base = ParsedWhatsappMessage(
                    message_id=str(msg.get("id") or ""),
                    sender_wa_id=str(msg.get("from") or ""),
                    phone_number_id=phone_number_id,
                    waba_id=waba_id,
                    msg_type=msg_type,
                    text=None,
                    media_id=None,
                    mime_type=None,
                    filename=None,
                    caption=None,
                )
                if msg_type == "text":
                    text_block = msg.get("text") or {}
                    base.text = str(text_block.get("body") or "") if isinstance(text_block, dict) else ""
                elif msg_type == "image":
                    block = msg.get("image") or {}
                    if isinstance(block, dict):
                        base.media_id = str(block.get("id") or "") or None
                        base.mime_type = str(block.get("mime_type") or "image/jpeg")
                        base.caption = str(block.get("caption") or "") or None
                elif msg_type == "document":
                    block = msg.get("document") or {}
                    if isinstance(block, dict):
                        base.media_id = str(block.get("id") or "") or None
                        base.mime_type = str(block.get("mime_type") or "application/pdf")
                        base.filename = str(block.get("filename") or "") or None
                        base.caption = str(block.get("caption") or "") or None
                elif msg_type == "interactive":
                    interactive = msg.get("interactive") or {}
                    if isinstance(interactive, dict):
                        button = interactive.get("button_reply") or interactive.get("list_reply")
                        if isinstance(button, dict):
                            base.text = str(button.get("title") or button.get("id") or "")
                            base.msg_type = "text"
                elif msg_type == "button":
                    button = msg.get("button") or {}
                    if isinstance(button, dict):
                        base.text = str(button.get("text") or "")
                        base.msg_type = "text"
                elif msg_type in {"reaction", "system"}:
                    base.skip_ai = True
                parsed.append(base)
    return parsed


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
