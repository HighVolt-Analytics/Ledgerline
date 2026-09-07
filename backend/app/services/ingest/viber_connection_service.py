"""CRUD and token helpers for connected Viber bots."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connected_viber import (
    STATUS_CONNECTED,
    STATUS_DISCONNECTED,
    ConnectedViberAccount,
)
from app.services.shared.public_api_url import webhook_viber_url
from app.services.shared.token_vault import decrypt_secret, encrypt_secret
from app.services.ingest.viber_client import ViberClient
from app.utils.logger import get_logger

logger = get_logger(__name__)


def resolve_auth_token(connection: ConnectedViberAccount) -> str:
    token = decrypt_secret(connection.auth_token_encrypted)
    if not token:
        raise RuntimeError("Viber auth token missing — reconnect the bot")
    return token


async def list_connections(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID | str | int,
) -> list[ConnectedViberAccount]:
    from app.tenant_ids import parse_tenant_id

    org_id = parse_tenant_id(tenant_id)
    if org_id is None:
        return []
    rows = (
        await session.execute(
            select(ConnectedViberAccount)
            .where(ConnectedViberAccount.tenant_id == org_id)
            .order_by(ConnectedViberAccount.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


async def test_connection(
    session: AsyncSession,
    connection: ConnectedViberAccount,
) -> dict:
    from app.models.connected_viber import STATUS_ACTION_REQUIRED, STATUS_CONNECTED

    token = resolve_auth_token(connection)
    client = ViberClient(token)
    profile = await client.get_account_info()
    warnings: list[str] = []
    try:
        await client.set_webhook(webhook_viber_url())
    except Exception as exc:
        warnings.append(f"Webhook resubscribe failed: {exc}")
        connection.integration_health = STATUS_ACTION_REQUIRED
    else:
        connection.integration_health = STATUS_CONNECTED

    await session.flush()
    return {
        "profile": profile,
        "warnings": warnings,
        "integration_health": connection.integration_health,
    }


async def get_connection_by_bot_id(
    session: AsyncSession,
    bot_id: str,
) -> ConnectedViberAccount | None:
    if not bot_id:
        return None
    return (
        await session.execute(
            select(ConnectedViberAccount).where(
                ConnectedViberAccount.bot_id == bot_id,
                ConnectedViberAccount.connection_status == STATUS_CONNECTED,
            )
        )
    ).scalar_one_or_none()


async def find_connection_by_signature(
    session: AsyncSession,
    raw_body: bytes,
    signature_header: str | None,
) -> ConnectedViberAccount | None:
    if not signature_header:
        return None
    rows = (
        await session.execute(
            select(ConnectedViberAccount).where(
                ConnectedViberAccount.connection_status == STATUS_CONNECTED,
                ConnectedViberAccount.auth_token_encrypted.isnot(None),
            )
        )
    ).scalars().all()
    for row in rows:
        try:
            token = resolve_auth_token(row)
        except RuntimeError:
            continue
        client = ViberClient(token)
        if client.verify_signature(raw_body, signature_header):
            return row
    return None


async def connect_viber_bot(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID | str | int,
    auth_token: str,
    webhook_base_url: str | None = None,
) -> ConnectedViberAccount:
    from app.tenant_ids import parse_tenant_id

    org_id = parse_tenant_id(tenant_id)
    if org_id is None:
        raise ValueError("Invalid tenant id")

    token = auth_token.strip()
    if not token:
        raise RuntimeError("Viber auth token is required")

    client = ViberClient(token)
    account_info = await client.get_account_info()
    bot_id = str(account_info.get("id") or "").strip()
    if not bot_id:
        raise RuntimeError("Viber get_account_info missing bot id")

    webhook_url = webhook_base_url.strip().rstrip("/") if webhook_base_url else webhook_viber_url()
    await client.set_webhook(webhook_url)

    existing = (
        await session.execute(
            select(ConnectedViberAccount).where(
                ConnectedViberAccount.tenant_id == org_id,
                ConnectedViberAccount.bot_id == bot_id,
            )
        )
    ).scalar_one_or_none()

    if existing:
        row = existing
    else:
        row = ConnectedViberAccount(tenant_id=org_id, bot_id=bot_id)
        session.add(row)

    row.auth_token_encrypted = encrypt_secret(token)
    row.connection_status = STATUS_CONNECTED
    row.integration_health = STATUS_CONNECTED
    await session.flush()

    logger.info(
        "viber_bot_connected",
        tenant_id=str(org_id),
        bot_id=bot_id,
        webhook_url=webhook_url,
    )
    return row


async def disconnect_connection(
    session: AsyncSession,
    connection: ConnectedViberAccount,
) -> None:
    try:
        token = decrypt_secret(connection.auth_token_encrypted)
        if token:
            await ViberClient(token).set_webhook("")
    except Exception as exc:
        logger.warning(
            "viber_webhook_unregister_failed",
            connection_id=connection.id,
            error=str(exc),
        )
    connection.connection_status = STATUS_DISCONNECTED
    connection.integration_health = STATUS_DISCONNECTED
    connection.auth_token_encrypted = None
    await session.flush()
