"""Enumerate tenant memberships at login."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_tenant_mapping import UserTenantMapping


@dataclass(frozen=True)
class TenantMembershipAccount:
    user_id: int
    tenant_id: int
    tenant_name: str
    tenant_slug: str
    role: str
    default_tenant: bool


async def list_memberships_for_auth_account(
    session: AsyncSession, *, auth_account_id: int
) -> list[TenantMembershipAccount]:
    rows = (
        await session.execute(
            select(User, Tenant, UserTenantMapping)
            .join(UserTenantMapping, UserTenantMapping.user_id == User.id)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(
                User.auth_account_id == auth_account_id,
                User.is_active.is_(True),
                UserTenantMapping.is_active.is_(True),
                UserTenantMapping.status == "active",
                Tenant.is_active.is_(True),
            )
            .order_by(Tenant.name)
        )
    ).all()

    accounts: list[TenantMembershipAccount] = []
    for user, tenant, mapping in rows:
        accounts.append(
            TenantMembershipAccount(
                user_id=user.id,
                tenant_id=tenant.id,
                tenant_name=tenant.name,
                tenant_slug=tenant.slug,
                role=mapping.role or user.role.value,
                default_tenant=mapping.default_tenant,
            )
        )
    return accounts
