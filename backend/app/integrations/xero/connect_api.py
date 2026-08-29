"""Xero Connect for existing HTTP routes. Does not import legacy accounting_integration_service."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.core.oauth_state import create_oauth_state
from app.integrations.xero.oauth import (
    OAUTH_STATE_TYP,
    PROVIDER,
    authorize_url,
    exchange_authorization_code,
    is_configured,
)
from app.integrations.xero.store import (
    apply_org_selection,
    list_connection_items,
    select_connection,
    upsert_connections,
    upsert_tokens,
)
from app.models.accounting_integration import AccountingIntegration


def build_connect_url(*, tenant_id: uuid.UUID, user_id: int) -> str:
    if not is_configured():
        raise RuntimeError("Xero credentials are not configured")
    state = create_oauth_state(
        provider=PROVIDER,
        tenant_id=tenant_id,
        user_id=user_id,
        typ=OAUTH_STATE_TYP,
    )
    return authorize_url(state=state)


async def complete_oauth_callback(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: int,
    code: str,
) -> AccountingIntegration:
    payload = await exchange_authorization_code(code)
    integration = await upsert_tokens(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        expires_at=payload["expires_at"],
        scopes=str(payload["scopes"]) if payload.get("scopes") else None,
    )
    persisted = await upsert_connections(
        db,
        integration=integration,
        tenant_id=tenant_id,
        connections=payload["connections"],
    )
    return await apply_org_selection(
        db,
        integration=integration,
        connections=persisted,
    )


async def list_xero_connections(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[dict]:
    return await list_connection_items(db, tenant_id)


async def select_xero_connection(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    xero_connection_id: str,
) -> AccountingIntegration:
    return await select_connection(
        db,
        tenant_id=tenant_id,
        xero_connection_id=xero_connection_id,
    )
