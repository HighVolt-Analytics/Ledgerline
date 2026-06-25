"""Enumerate tenant memberships at login and for the tenant switcher."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_account import AuthAccount
from app.models.tenant import Tenant
from app.models.user import SUPER_ADMIN_ROLE, User
from app.models.user_tenant_mapping import UserTenantMapping


@dataclass(frozen=True)
class TenantMembershipAccount:
    user_id: int
    tenant_id: uuid.UUID
    tenant_name: str
    tenant_slug: str
    role: str
    default_tenant: bool
    is_platform: bool = False
    is_platform_shadow: bool = False


def membership_is_switchable(m: TenantMembershipAccount) -> bool:
    """Client tenants are listed for real users only; platform tenant for super admins."""
    if m.is_platform_shadow:
        return False
    if not m.is_platform:
        return True
    return m.role == SUPER_ADMIN_ROLE


def filter_switchable_memberships(
    memberships: list[TenantMembershipAccount],
) -> list[TenantMembershipAccount]:
    return [m for m in memberships if membership_is_switchable(m)]


async def list_memberships_for_auth_account(
    session: AsyncSession, *, auth_account_id: int
) -> list[TenantMembershipAccount]:
    account = await session.get(AuthAccount, auth_account_id)
    if not account:
        return []

    rows = (
        await session.execute(
            select(User, Tenant, UserTenantMapping)
            .join(UserTenantMapping, UserTenantMapping.user_id == User.id)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(
                User.auth_account_id == auth_account_id,
                User.is_active.is_(True),
                User.is_platform_shadow.is_(False),
                UserTenantMapping.is_active.is_(True),
                UserTenantMapping.status == "active",
                Tenant.is_active.is_(True),
            )
            .order_by(Tenant.name)
        )
    ).all()

    by_tenant: dict[int, TenantMembershipAccount] = {}
    for user, tenant, mapping in rows:
        by_tenant[tenant.id] = TenantMembershipAccount(
            user_id=user.id,
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            tenant_slug=tenant.slug,
            role=mapping.role or user.role.value,
            default_tenant=mapping.default_tenant,
            is_platform=tenant.is_platform,
            is_platform_shadow=user.is_platform_shadow,
        )

    # Email pivot: same human may have per-tenant user rows before full mapping backfill.
    email_rows = (
        await session.execute(
            select(User, Tenant)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(
                User.email.ilike(account.email),
                User.is_active.is_(True),
                User.is_platform_shadow.is_(False),
                Tenant.is_active.is_(True),
            )
            .order_by(Tenant.name)
        )
    ).all()

    for user, tenant in email_rows:
        if tenant.id in by_tenant:
            continue
        mapping = (
            await session.execute(
                select(UserTenantMapping).where(
                    UserTenantMapping.user_id == user.id,
                    UserTenantMapping.tenant_id == tenant.id,
                    UserTenantMapping.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        by_tenant[tenant.id] = TenantMembershipAccount(
            user_id=user.id,
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            tenant_slug=tenant.slug,
            role=(mapping.role if mapping else None) or user.role.value,
            default_tenant=bool(mapping.default_tenant) if mapping else False,
            is_platform=tenant.is_platform,
            is_platform_shadow=user.is_platform_shadow,
        )

    return sorted(by_tenant.values(), key=lambda item: item.tenant_name)
