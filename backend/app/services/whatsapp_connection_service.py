"""CRUD and token helpers for connected WhatsApp accounts."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.connected_whatsapp import (
    STATUS_ACTION_REQUIRED,
    STATUS_CONNECTED,
    STATUS_DISCONNECTED,
    ConnectedWhatsapp,
)
from app.models.meta_webhook_dedupe import MetaWebhookDedupe
from app.services.token_vault import decrypt_secret, encrypt_secret
from app.services.whatsapp_graph_client import (
    WhatsappPhoneNumber,
    discover_waba_ids,
    discover_whatsapp_phones,
    exchange_code_for_token,
    exchange_long_lived_token,
    subscribe_waba_webhooks,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

STATE_TYP = "whatsapp_oauth"
STATE_TTL_MINUTES = 20


def oauth_configured() -> bool:
    return get_settings().whatsapp_configured


def create_oauth_state(*, tenant_id: int, user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MINUTES)
    payload: dict[str, Any] = {
        "typ": STATE_TYP,
        "org_id": tenant_id,
        # PyJWT requires sub to be a string (RFC 7519).
        "sub": str(user_id),
        "exp": expire,
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def parse_oauth_state(state: str) -> dict[str, Any]:
    payload = jwt.decode(state, get_settings().jwt_secret, algorithms=["HS256"])
    if payload.get("typ") != STATE_TYP:
        raise ValueError("Invalid OAuth state")
    return payload


async def list_connections(
    session: AsyncSession,
    *,
    tenant_id: int,
) -> list[ConnectedWhatsapp]:
    rows = (
        await session.execute(
            select(ConnectedWhatsapp)
            .where(ConnectedWhatsapp.tenant_id == tenant_id)
            .order_by(ConnectedWhatsapp.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


async def find_connection_by_phone_or_waba(
    session: AsyncSession,
    *,
    phone_number_id: str | None,
    waba_id: str | None = None,
) -> ConnectedWhatsapp | None:
    if phone_number_id:
        row = (
            await session.execute(
                select(ConnectedWhatsapp).where(
                    ConnectedWhatsapp.phone_number_id == phone_number_id,
                    ConnectedWhatsapp.connection_status == STATUS_CONNECTED,
                )
            )
        ).scalar_one_or_none()
        if row:
            return row
    if waba_id:
        return (
            await session.execute(
                select(ConnectedWhatsapp).where(
                    ConnectedWhatsapp.whatsapp_business_account_id == waba_id,
                    ConnectedWhatsapp.connection_status == STATUS_CONNECTED,
                )
            )
        ).scalar_one_or_none()
    return None


async def try_claim_message_mid(
    session: AsyncSession,
    message_mid: str,
    *,
    tenant_id: uuid.UUID,
) -> bool:
    if not message_mid:
        return False
    existing = (
        await session.execute(
            select(MetaWebhookDedupe.id).where(
                MetaWebhookDedupe.tenant_id == tenant_id,
                MetaWebhookDedupe.message_mid == message_mid,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False
    session.add(MetaWebhookDedupe(tenant_id=tenant_id, message_mid=message_mid))
    await session.flush()
    return True


def resolve_access_token(connection: ConnectedWhatsapp) -> str:
    token = decrypt_secret(connection.access_token_encrypted)
    if not token:
        raise RuntimeError("WhatsApp access token missing — reconnect the account")
    return token


async def upsert_phone_connection(
    session: AsyncSession,
    *,
    tenant_id: int,
    phone: WhatsappPhoneNumber,
    access_token: str,
    token_expires_at: datetime | None,
    connected_by_user_id: int | None,
) -> ConnectedWhatsapp:
    existing = (
        await session.execute(
            select(ConnectedWhatsapp).where(
                ConnectedWhatsapp.tenant_id == tenant_id,
                ConnectedWhatsapp.phone_number_id == phone.phone_number_id,
            )
        )
    ).scalar_one_or_none()

    if existing:
        row = existing
    else:
        row = ConnectedWhatsapp(tenant_id=tenant_id, phone_number_id=phone.phone_number_id)
        session.add(row)

    row.phone_number = phone.display_phone_number or row.phone_number
    row.display_name = phone.verified_name or row.display_name
    row.whatsapp_business_account_id = phone.waba_id
    row.access_token_encrypted = encrypt_secret(access_token)
    row.token_expires_at = token_expires_at
    row.connection_status = STATUS_CONNECTED
    row.integration_health = STATUS_CONNECTED
    row.connected_by_user_id = connected_by_user_id
    row.last_error = None
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return row


async def complete_oauth_and_store_connections(
    session: AsyncSession,
    *,
    code: str,
    tenant_id: int,
    user_id: int,
) -> list[ConnectedWhatsapp]:
    logger.info("whatsapp_oauth_start", tenant_id=tenant_id, user_id=user_id)
    short = await exchange_code_for_token(code)
    short_token = str(short.get("access_token") or "")
    if not short_token:
        raise RuntimeError("OAuth response missing access_token")

    long = await exchange_long_lived_token(short_token)
    access_token = str(long.get("access_token") or short_token)
    expires_in = int(long.get("expires_in") or short.get("expires_in") or 5184000)
    token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    phones = await discover_whatsapp_phones(access_token)
    if not phones:
        waba_ids = await discover_waba_ids(access_token)
        if not waba_ids:
            logger.warning("whatsapp_oauth_no_waba", tenant_id=tenant_id)
            raise RuntimeError("no_waba")
        logger.warning("whatsapp_oauth_no_phone", tenant_id=tenant_id, waba_ids=waba_ids)
        raise RuntimeError("no_phone")

    stored: list[ConnectedWhatsapp] = []
    subscribed_wabas: set[str] = set()
    for phone in phones:
        if phone.waba_id and phone.waba_id not in subscribed_wabas:
            subscribed_wabas.add(phone.waba_id)
            try:
                await subscribe_waba_webhooks(phone.waba_id, access_token=access_token)
            except Exception as exc:
                logger.warning(
                    "whatsapp_subscribe_failed",
                    waba_id=phone.waba_id,
                    error=str(exc),
                )

        row = await upsert_phone_connection(
            session,
            tenant_id=tenant_id,
            phone=phone,
            access_token=access_token,
            token_expires_at=token_expires_at,
            connected_by_user_id=user_id,
        )
        stored.append(row)

    await session.flush()
    logger.info(
        "whatsapp_oauth_connected",
        tenant_id=tenant_id,
        phones=len(stored),
        phone_number_ids=[row.phone_number_id for row in stored],
    )
    return stored


async def disconnect_connection(
    session: AsyncSession,
    connection: ConnectedWhatsapp,
) -> None:
    connection.connection_status = STATUS_DISCONNECTED
    connection.integration_health = STATUS_DISCONNECTED
    connection.access_token_encrypted = None
    connection.token_expires_at = None
    connection.last_error = None
    connection.updated_at = datetime.now(timezone.utc)
    await session.flush()


async def resubscribe_connection_webhooks(connection: ConnectedWhatsapp) -> None:
    waba_id = connection.whatsapp_business_account_id
    if not waba_id:
        return
    token = resolve_access_token(connection)
    await subscribe_waba_webhooks(waba_id, access_token=token)


async def test_connection(
    session: AsyncSession,
    connection: ConnectedWhatsapp,
) -> dict[str, Any]:
    token = resolve_access_token(connection)
    profile = await get_phone_profile_safe(connection.phone_number_id, access_token=token)
    connection.last_sync_at = datetime.now(timezone.utc)
    connection.last_error = None

    status = str(profile.get("status") or "").upper()
    platform = str(profile.get("platform_type") or "").upper()
    health = STATUS_CONNECTED
    warnings: list[str] = []
    if status and status not in {"CONNECTED", "LIVE"}:
        health = STATUS_ACTION_REQUIRED
        warnings.append(f"Phone status is {status}")
    if platform and platform not in {"CLOUD_API", "NOT_APPLICABLE", ""}:
        health = STATUS_ACTION_REQUIRED
        warnings.append(f"Platform type is {platform} — Cloud API required")

    connection.integration_health = health
    if warnings:
        connection.last_error = "; ".join(warnings)[:512]

    if connection.whatsapp_business_account_id:
        try:
            await subscribe_waba_webhooks(
                connection.whatsapp_business_account_id,
                access_token=token,
            )
        except Exception as exc:
            warnings.append(f"Webhook resubscribe failed: {exc}")

    await session.flush()
    return {
        "profile": profile,
        "warnings": warnings,
        "integration_health": connection.integration_health,
    }


async def get_phone_profile_safe(
    phone_number_id: str,
    *,
    access_token: str,
) -> dict[str, Any]:
    from app.services.whatsapp_graph_client import get_phone_profile

    return await get_phone_profile(phone_number_id, access_token=access_token)
