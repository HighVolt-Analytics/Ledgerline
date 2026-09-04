"""Persist Xero OAuth tokens and organisation rows. Uses existing tables, not legacy services."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.core.token_crypto import encrypt_secret
from app.models.accounting_integration import (
    AccountingIntegration,
    AccountingIntegrationStatus,
    AccountingProvider,
)
from app.models.xero_connection import XeroConnection

XERO_ORGANISATION_TYPE = "ORGANISATION"


class XeroNotReadyError(RuntimeError):
    """Xero is disconnected, needs org selection, or needs re-auth."""


async def get_xero_integration(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> AccountingIntegration | None:
    return (
        await db.execute(
            select(AccountingIntegration).where(
                AccountingIntegration.tenant_id == tenant_id,
                AccountingIntegration.provider == AccountingProvider.XERO.value,
            )
        )
    ).scalar_one_or_none()


async def upsert_tokens(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: int,
    access_token: str,
    refresh_token: str | None,
    expires_at: datetime | None,
    scopes: str | None,
) -> AccountingIntegration:
    row = await get_xero_integration(db, tenant_id)
    now = datetime.now(timezone.utc)
    if row is None:
        row = AccountingIntegration(
            tenant_id=tenant_id,
            provider=AccountingProvider.XERO.value,
        )
        db.add(row)
    row.status = AccountingIntegrationStatus.ORGANISATION_SELECTION_REQUIRED.value
    row.provider_tenant_id = None
    row.xero_connection_id = None
    row.provider_tenant_type = None
    row.display_name = None
    row.access_token_encrypted = encrypt_secret(access_token)
    row.refresh_token_encrypted = encrypt_secret(refresh_token) if refresh_token else None
    row.expires_at = expires_at
    row.scopes = scopes
    row.connected_by_user_id = user_id
    row.connected_at = now
    row.last_error = None
    row.last_error_code = None
    row.token_version = int(row.token_version or 0)
    await db.flush()
    return row


async def upsert_connections(
    db: AsyncSession,
    *,
    integration: AccountingIntegration,
    tenant_id: uuid.UUID,
    connections: list[dict[str, Any]],
) -> list[XeroConnection]:
    now = datetime.now(timezone.utc)
    existing = (
        await db.execute(
            select(XeroConnection).where(
                XeroConnection.accounting_integration_id == integration.id,
            )
        )
    ).scalars().all()
    by_connection_id = {row.xero_connection_id: row for row in existing}
    by_xero_tenant = {row.xero_tenant_id: row for row in existing}
    persisted: list[XeroConnection] = []
    seen_ids: set[str] = set()

    for conn in connections:
        connection_id = str(conn.get("id") or "")
        xero_tenant = str(conn.get("tenantId") or "")
        if not connection_id or not xero_tenant:
            continue
        seen_ids.add(connection_id)
        row = by_connection_id.get(connection_id)
        if row is None:
            # Reconnect: Xero issues a new connection id for the same org.
            # uq_xero_connections_tenant_xero_tenant forbids a second INSERT.
            row = by_xero_tenant.get(xero_tenant)
            if row is not None:
                previous_connection_id = row.xero_connection_id
                row.xero_connection_id = connection_id
                by_connection_id.pop(previous_connection_id, None)
                by_connection_id[connection_id] = row
        if row is None:
            row = XeroConnection(
                accounting_integration_id=integration.id,
                tenant_id=tenant_id,
                xero_connection_id=connection_id,
                xero_tenant_id=xero_tenant,
            )
            db.add(row)
            by_connection_id[connection_id] = row
            by_xero_tenant[xero_tenant] = row
        row.xero_tenant_id = xero_tenant
        row.xero_tenant_type = str(conn.get("tenantType") or "") or None
        row.xero_tenant_name = str(conn.get("tenantName") or xero_tenant) or None
        row.active = True
        row.connected_at = now
        row.last_verified_at = now
        row.disconnected_at = None
        persisted.append(row)

    for row in existing:
        if row.xero_connection_id not in seen_ids:
            row.active = False
            row.selected = False
            row.disconnected_at = now

    await db.flush()
    return persisted


async def apply_org_selection(
    db: AsyncSession,
    *,
    integration: AccountingIntegration,
    connections: list[XeroConnection],
) -> AccountingIntegration:
    organisations = [
        c
        for c in connections
        if c.active and (c.xero_tenant_type or "").upper() == XERO_ORGANISATION_TYPE
    ]
    await db.execute(
        update(XeroConnection)
        .where(XeroConnection.accounting_integration_id == integration.id)
        .values(selected=False)
    )
    if len(organisations) == 1:
        org = organisations[0]
        org.selected = True
        integration.provider_tenant_id = org.xero_tenant_id
        integration.xero_connection_id = org.xero_connection_id
        integration.provider_tenant_type = org.xero_tenant_type
        integration.display_name = org.xero_tenant_name
        integration.status = AccountingIntegrationStatus.CONNECTED.value
    elif len(organisations) > 1:
        integration.provider_tenant_id = None
        integration.xero_connection_id = None
        integration.provider_tenant_type = None
        integration.display_name = None
        integration.status = AccountingIntegrationStatus.ORGANISATION_SELECTION_REQUIRED.value
    else:
        raise RuntimeError("No Xero organisations available for this account")
    await db.flush()
    return integration


async def list_connection_items(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[dict[str, Any]]:
    integration = await get_xero_integration(db, tenant_id)
    if integration is None:
        return []
    rows = (
        await db.execute(
            select(XeroConnection)
            .where(
                XeroConnection.accounting_integration_id == integration.id,
                XeroConnection.active.is_(True),
            )
            .order_by(XeroConnection.xero_tenant_name.asc())
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "xero_connection_id": row.xero_connection_id,
            "xero_tenant_id": row.xero_tenant_id,
            "xero_tenant_type": row.xero_tenant_type,
            "xero_tenant_name": row.xero_tenant_name,
            "selected": row.selected,
        }
        for row in rows
    ]


async def select_connection(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    xero_connection_id: str,
) -> AccountingIntegration:
    integration = await get_xero_integration(db, tenant_id)
    if integration is None:
        raise ValueError("Xero is not connected")

    row = (
        await db.execute(
            select(XeroConnection).where(
                XeroConnection.tenant_id == tenant_id,
                XeroConnection.accounting_integration_id == integration.id,
                XeroConnection.xero_connection_id == xero_connection_id,
                XeroConnection.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError("Xero connection not found")
    if (row.xero_tenant_type or "").upper() != XERO_ORGANISATION_TYPE:
        raise ValueError("Only organisation connections can be selected")

    await db.execute(
        update(XeroConnection)
        .where(
            XeroConnection.accounting_integration_id == integration.id,
            XeroConnection.tenant_id == tenant_id,
        )
        .values(selected=False)
    )
    row.selected = True
    integration.provider_tenant_id = row.xero_tenant_id
    integration.xero_connection_id = row.xero_connection_id
    integration.provider_tenant_type = row.xero_tenant_type
    integration.display_name = row.xero_tenant_name
    integration.status = AccountingIntegrationStatus.CONNECTED.value
    integration.last_error = None
    integration.last_error_code = None
    await db.flush()
    return integration


async def require_xero_ready(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> tuple[AccountingIntegration, str]:
    integration = await get_xero_integration(db, tenant_id)
    if integration is None:
        raise XeroNotReadyError("Xero integration is not ready")
    if integration.status == AccountingIntegrationStatus.ORGANISATION_SELECTION_REQUIRED.value:
        raise XeroNotReadyError("Select a Xero organisation before continuing")
    if integration.status == AccountingIntegrationStatus.NEEDS_REAUTH.value:
        raise XeroNotReadyError("Xero connection requires re-authentication")
    if (
        integration.status != AccountingIntegrationStatus.CONNECTED.value
        or not integration.provider_tenant_id
        or not integration.access_token_encrypted
    ):
        raise XeroNotReadyError("Xero integration is not ready")
    return integration, integration.provider_tenant_id
