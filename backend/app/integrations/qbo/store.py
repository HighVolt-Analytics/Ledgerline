"""Persist QuickBooks connection readiness."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting_integration import (
    AccountingIntegration,
    AccountingIntegrationStatus,
    AccountingProvider,
)


class QboNotReadyError(RuntimeError):
    """QuickBooks is disconnected or needs re-auth."""


async def get_qbo_integration(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> AccountingIntegration | None:
    return (
        await db.execute(
            select(AccountingIntegration).where(
                AccountingIntegration.tenant_id == tenant_id,
                AccountingIntegration.provider == AccountingProvider.QUICKBOOKS_ONLINE.value,
            )
        )
    ).scalar_one_or_none()


async def require_qbo_ready(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> tuple[AccountingIntegration, str]:
    integration = await get_qbo_integration(db, tenant_id)
    if integration is None:
        raise QboNotReadyError("QuickBooks is not connected")
    if integration.status == AccountingIntegrationStatus.NEEDS_REAUTH.value:
        raise QboNotReadyError("QuickBooks connection requires re-authentication")
    realm_id = (integration.provider_tenant_id or "").strip()
    if (
        integration.status != AccountingIntegrationStatus.CONNECTED.value
        or not realm_id
        or not integration.access_token_encrypted
    ):
        raise QboNotReadyError("QuickBooks is not connected")
    return integration, realm_id
