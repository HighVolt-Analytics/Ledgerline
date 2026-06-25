"""Active tenant gate."""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.models.user import User


async def assert_tenant_active(tenant: Tenant | None) -> None:
    if not tenant or not tenant.is_active or tenant.lifecycle_status != "active":
        raise HTTPException(403, "Tenant access suspended")


async def assert_tenant_active_for_user(session: AsyncSession, user: User | None) -> None:
    if user is None:
        return
    tenant = await session.get(Tenant, user.tenant_id)
    await assert_tenant_active(tenant)
