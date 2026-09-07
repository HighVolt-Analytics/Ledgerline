"""Enumerate tenant memberships at login and for the tenant switcher."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_account import AuthAccount
from app.models.tenant import Tenant
from app.models.user import SUPER_ADMIN_ROLE, User
from app.models.user_tenant_mapping import UserTenantMapping
from app.utils.logger import get_logger

logger = get_logger(__name__)


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


def membership_log_summary(m: TenantMembershipAccount) -> dict[str, Any]:
    return {
        "user_id": m.user_id,
        "tenant_id": str(m.tenant_id),
        "tenant_slug": m.tenant_slug,
        "role": m.role,
        "default_tenant": m.default_tenant,
        "is_platform": m.is_platform,
        "switchable": membership_is_switchable(m),
    }


def log_membership_enumeration(
    *,
    auth_account_id: int,
    email: str,
    source: str,
    all_memberships: list[TenantMembershipAccount],
    mapping_count: int = 0,
    email_pivot_added: int = 0,
) -> list[TenantMembershipAccount]:
    """Filter to switchable memberships and emit a structured audit log."""
    switchable = filter_switchable_memberships(all_memberships)
    hidden = [m for m in all_memberships if not membership_is_switchable(m)]

    logger.info(
        "login_memberships_enumerated",
        source=source,
        email=email,
        auth_account_id=auth_account_id,
        mapping_count=mapping_count,
        email_pivot_added=email_pivot_added,
        total_linked=len(all_memberships),
        switchable_count=len(switchable),
        hidden_count=len(hidden),
        switchable_accounts=[membership_log_summary(m) for m in switchable],
        hidden_accounts=[membership_log_summary(m) for m in hidden],
    )
    return switchable


async def list_memberships_for_auth_account(
    session: AsyncSession,
    *,
    auth_account_id: int,
    log_source: str | None = None,
) -> list[TenantMembershipAccount]:
    account = await session.get(AuthAccount, auth_account_id)
    if not account:
        if log_source:
            logger.info(
                "login_memberships_skipped",
                source=log_source,
                auth_account_id=auth_account_id,
                reason="auth_account_not_found",
            )
        return []

    if log_source:
        logger.info(
            "login_memberships_lookup_started",
            source=log_source,
            auth_account_id=auth_account_id,
            email=account.email,
        )

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

    by_tenant: dict[uuid.UUID, TenantMembershipAccount] = {}
    mapping_count = 0
    for user, tenant, mapping in rows:
        mapping_count += 1
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

    email_pivot_added = 0
    for user, tenant in email_rows:
        if tenant.id in by_tenant:
            continue
        email_pivot_added += 1
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

    all_memberships = sorted(by_tenant.values(), key=lambda item: item.tenant_name)
    if log_source:
        log_membership_enumeration(
            auth_account_id=auth_account_id,
            email=account.email,
            source=log_source,
            all_memberships=all_memberships,
            mapping_count=mapping_count,
            email_pivot_added=email_pivot_added,
        )
    return all_memberships


async def list_memberships_for_auth_account_resilient(
    session: AsyncSession,
    *,
    auth_account_id: int,
    log_source: str | None = None,
    restore_platform_lookup: bool = True,
) -> list[TenantMembershipAccount]:
    """Same as list_memberships_for_auth_account, with retries on dropped DB sockets.

    Login/OTP often sits on a pooled connection while Redis OTP work runs; Azure (or
    the network) may close that socket before the memberships JOIN. Retry with a
    fresh connection and re-apply platform-lookup GUC when needed.
    """
    from app.db_transient import run_with_transient_db_retry
    from app.tenant_rls import apply_platform_lookup_session

    async def _run() -> list[TenantMembershipAccount]:
        if restore_platform_lookup:
            await apply_platform_lookup_session(session)
        return await list_memberships_for_auth_account(
            session,
            auth_account_id=auth_account_id,
            log_source=log_source,
        )

    return await run_with_transient_db_retry(session, _run, attempts=3)
