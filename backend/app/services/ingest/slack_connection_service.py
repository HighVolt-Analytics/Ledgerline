"""CRUD and token helpers for connected Slack workspaces."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.connected_slack import (
    STATUS_CONNECTED,
    STATUS_DISCONNECTED,
    ConnectedSlackAccount,
)
from app.models.slack_webhook_dedupe import SlackWebhookDedupe
from app.services.shared.token_vault import decrypt_secret, encrypt_secret
from app.services.ingest.slack_web_client import (
    auth_test,
    exchange_code_for_token,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

STATE_TYP = "slack_oauth"
STATE_TTL_MINUTES = 20


def oauth_configured() -> bool:
    return get_settings().slack_configured


def create_oauth_state(*, tenant_id: uuid.UUID | str | int, user_id: int) -> str:
    from app.tenant_ids import parse_tenant_id

    org_id = parse_tenant_id(tenant_id)
    if org_id is None:
        raise ValueError("Invalid tenant id")
    expire = datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MINUTES)
    payload: dict[str, Any] = {
        "typ": STATE_TYP,
        "org_id": str(org_id),
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
    tenant_id: uuid.UUID,
) -> list[ConnectedSlackAccount]:
    rows = (
        await session.execute(
            select(ConnectedSlackAccount)
            .where(ConnectedSlackAccount.tenant_id == tenant_id)
            .order_by(ConnectedSlackAccount.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


async def find_connection_by_team_id(
    session: AsyncSession,
    *,
    team_id: str,
    connected_only: bool = True,
) -> ConnectedSlackAccount | None:
    if not team_id:
        return None
    stmt = select(ConnectedSlackAccount).where(ConnectedSlackAccount.team_id == team_id)
    if connected_only:
        stmt = stmt.where(ConnectedSlackAccount.connection_status == STATUS_CONNECTED)
    stmt = stmt.order_by(ConnectedSlackAccount.updated_at.desc())
    return (await session.execute(stmt)).scalars().first()


async def try_claim_event_id(
    session: AsyncSession,
    event_id: str,
    *,
    tenant_id: uuid.UUID,
) -> bool:
    if not event_id:
        return False
    existing = (
        await session.execute(
            select(SlackWebhookDedupe.id).where(
                SlackWebhookDedupe.tenant_id == tenant_id,
                SlackWebhookDedupe.event_id == event_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False
    from sqlalchemy.exc import IntegrityError

    try:
        async with session.begin_nested():
            session.add(SlackWebhookDedupe(tenant_id=tenant_id, event_id=event_id))
            await session.flush()
    except IntegrityError:
        return False
    return True


def resolve_access_token(connection: ConnectedSlackAccount) -> str:
    token = decrypt_secret(connection.access_token_encrypted)
    if not token:
        raise RuntimeError("Slack bot token missing — reconnect the workspace")
    return token


async def upsert_workspace_connection(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    team_id: str,
    team_name: str | None,
    bot_user_id: str | None,
    app_id: str | None,
    access_token: str,
    connected_by_user_id: int | None,
) -> ConnectedSlackAccount:
    existing = (
        await session.execute(
            select(ConnectedSlackAccount).where(
                ConnectedSlackAccount.tenant_id == tenant_id,
                ConnectedSlackAccount.team_id == team_id,
            )
        )
    ).scalar_one_or_none()

    if existing:
        row = existing
    else:
        row = ConnectedSlackAccount(tenant_id=tenant_id, team_id=team_id)
        session.add(row)

    row.team_name = team_name or row.team_name
    row.bot_user_id = bot_user_id or row.bot_user_id
    row.app_id = app_id or row.app_id
    row.access_token_encrypted = encrypt_secret(access_token)
    row.connection_status = STATUS_CONNECTED
    row.integration_health = STATUS_CONNECTED
    row.connected_by_user_id = connected_by_user_id
    row.last_error = None
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return row


async def complete_oauth_and_store_connection(
    session: AsyncSession,
    *,
    code: str,
    tenant_id: uuid.UUID,
    user_id: int,
) -> ConnectedSlackAccount:
    logger.info("slack_oauth_start", tenant_id=str(tenant_id), user_id=user_id)
    payload = await exchange_code_for_token(code)
    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("OAuth response missing access_token")

    team = payload.get("team") if isinstance(payload.get("team"), dict) else {}
    team_id = str(team.get("id") or payload.get("team_id") or "").strip()
    team_name = str(team.get("name") or "") or None
    if not team_id:
        raise RuntimeError("OAuth response missing team_id")

    bot_user_id = str(payload.get("bot_user_id") or "") or None
    app_id = str(payload.get("app_id") or get_settings().slack_app_id or "") or None

    row = await upsert_workspace_connection(
        session,
        tenant_id=tenant_id,
        team_id=team_id,
        team_name=team_name,
        bot_user_id=bot_user_id,
        app_id=app_id,
        access_token=access_token,
        connected_by_user_id=user_id,
    )
    logger.info(
        "slack_oauth_connected",
        tenant_id=str(tenant_id),
        team_id=team_id,
        team_name=team_name,
    )
    return row


async def disconnect_connection(
    session: AsyncSession,
    connection: ConnectedSlackAccount,
    *,
    reason: str | None = None,
) -> None:
    connection.connection_status = STATUS_DISCONNECTED
    connection.integration_health = STATUS_DISCONNECTED
    connection.access_token_encrypted = None
    connection.last_error = (reason or "")[:512] or None
    connection.updated_at = datetime.now(timezone.utc)
    await session.flush()


async def mark_connection_revoked(
    session: AsyncSession,
    connection: ConnectedSlackAccount,
    *,
    event_type: str,
) -> None:
    """Flip status on app_uninstalled / tokens_revoked (idempotent cleanup)."""
    await disconnect_connection(
        session,
        connection,
        reason=f"slack_{event_type}",
    )


async def test_connection(
    session: AsyncSession,
    connection: ConnectedSlackAccount,
) -> dict[str, Any]:
    token = resolve_access_token(connection)
    profile = await auth_test(token)
    connection.last_sync_at = datetime.now(timezone.utc)
    connection.last_error = None
    connection.integration_health = STATUS_CONNECTED
    team = str(profile.get("team") or "") or None
    if team:
        connection.team_name = team
    bot_id = str(profile.get("user_id") or "") or None
    if bot_id:
        connection.bot_user_id = bot_id
    await session.flush()
    return {
        "profile": profile,
        "warnings": [],
        "integration_health": connection.integration_health,
    }
