"""Tenant membership helpers."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.models.user_tenant_mapping import UserTenantMapping


async def ensure_membership(
    session: AsyncSession,
    *,
    user_id: int,
    tenant_id: uuid.UUID,
    role: str = "member",
) -> None:
    existing = (
        await session.execute(
            select(UserTenantMapping).where(
                UserTenantMapping.user_id == user_id,
                UserTenantMapping.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return
    session.add(
        UserTenantMapping(
            user_id=user_id,
            tenant_id=tenant_id,
            role=role,
            status="active",
            is_active=True,
        )
    )
    await session.flush()


async def user_has_tenant_access(
    session: AsyncSession, *, user_id: int, tenant_id: uuid.UUID
) -> bool:
    row = (
        await session.execute(
            select(UserTenantMapping.id).where(
                UserTenantMapping.user_id == user_id,
                UserTenantMapping.tenant_id == tenant_id,
                UserTenantMapping.is_active.is_(True),
                UserTenantMapping.status == "active",
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def list_user_tenants(
    session: AsyncSession, *, user_id: int | None, current_tenant_id: uuid.UUID
) -> list[Tenant]:
    if user_id is None:
        tenant = await session.get(Tenant, current_tenant_id)
        return [tenant] if tenant else []

    rows = (
        await session.execute(
            select(Tenant)
            .join(UserTenantMapping, UserTenantMapping.tenant_id == Tenant.id)
            .where(
                UserTenantMapping.user_id == user_id,
                UserTenantMapping.is_active.is_(True),
            )
            .order_by(Tenant.name)
        )
    ).scalars().all()

    if rows:
        return list(rows)

    tenant = await session.get(Tenant, current_tenant_id)
    return [tenant] if tenant else []


async def get_membership_role(
    session: AsyncSession, *, user_id: int, tenant_id: uuid.UUID
) -> str | None:
    row = (
        await session.execute(
            select(UserTenantMapping.role).where(
                UserTenantMapping.user_id == user_id,
                UserTenantMapping.tenant_id == tenant_id,
                UserTenantMapping.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    return row
