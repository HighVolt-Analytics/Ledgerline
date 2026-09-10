"""Postgres persistence for per-tenant approval policy."""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant_approval_policy import TenantApprovalPolicy


async def fetch_policy_dict(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> dict[str, Any] | None:
    row = await session.get(TenantApprovalPolicy, tenant_id)
    if row is None:
        return None
    return deepcopy(row.config) if isinstance(row.config, dict) else None


async def upsert_policy(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    config: dict[str, Any],
    *,
    updated_by_user_id: int | None = None,
) -> dict[str, Any]:
    payload = deepcopy(config)
    row = await session.get(TenantApprovalPolicy, tenant_id)
    if row is None:
        row = TenantApprovalPolicy(
            tenant_id=tenant_id,
            config=payload,
            schema_version=1,
            updated_by_user_id=updated_by_user_id,
        )
        session.add(row)
    else:
        row.config = payload
        row.schema_version = 1
        if updated_by_user_id is not None:
            row.updated_by_user_id = updated_by_user_id
    await session.flush()
    return deepcopy(row.config)


async def delete_policy(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    row = await session.get(TenantApprovalPolicy, tenant_id)
    if row is not None:
        await session.delete(row)
        await session.flush()
