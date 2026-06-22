"""Seed platform tenant and super admin user (idempotent).

Run from backend/ with the same Python env as the API:

    python scripts/seed_super_admin.py
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select, text

from app.database import async_session_factory
from app.models.auth_account import AuthAccount
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.user_tenant_mapping import UserTenantMapping
from app.services.membership_service import ensure_membership

_SUPER_ADMIN_EMAIL = "vishnu@highvolt.tech"
_PLATFORM_SLUG = "platform"


async def seed_super_admin() -> None:
    async with async_session_factory() as session:
        await session.execute(
            text("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'super_admin'")
        )

        platform = (
            await session.execute(select(Tenant).where(Tenant.slug == _PLATFORM_SLUG))
        ).scalar_one_or_none()
        if platform is None:
            platform = Tenant(
                name="LedgerLink Platform",
                slug=_PLATFORM_SLUG,
                is_active=True,
                is_platform=True,
                lifecycle_status="active",
            )
            session.add(platform)
            await session.flush()

        source_user = (
            await session.execute(
                select(User).where(User.email.ilike(_SUPER_ADMIN_EMAIL)).order_by(User.id)
            )
        ).scalars().first()
        if not source_user:
            print(f"No user found for {_SUPER_ADMIN_EMAIL}; create the account first.")
            await session.commit()
            return

        auth_account_id = source_user.auth_account_id
        if auth_account_id is None:
            account = (
                await session.execute(
                    select(AuthAccount).where(AuthAccount.email.ilike(_SUPER_ADMIN_EMAIL))
                )
            ).scalar_one_or_none()
            if account is None:
                account = AuthAccount(
                    email=_SUPER_ADMIN_EMAIL.lower(),
                    password_hash=source_user.password_hash,
                )
                session.add(account)
                await session.flush()
            auth_account_id = account.id
            source_user.auth_account_id = auth_account_id

        platform_user = (
            await session.execute(
                select(User).where(
                    User.tenant_id == platform.id,
                    User.email.ilike(_SUPER_ADMIN_EMAIL),
                )
            )
        ).scalar_one_or_none()
        if platform_user is None:
            platform_user = User(
                tenant_id=platform.id,
                auth_account_id=auth_account_id,
                email=_SUPER_ADMIN_EMAIL.lower(),
                password_hash=source_user.password_hash,
                full_name=source_user.full_name or "Vishnu",
                role=UserRole.SUPER_ADMIN,
                is_active=True,
            )
            session.add(platform_user)
            await session.flush()
        else:
            platform_user.role = UserRole.SUPER_ADMIN
            platform_user.is_active = True
            platform_user.auth_account_id = auth_account_id

        await ensure_membership(
            session,
            user_id=platform_user.id,
            tenant_id=platform.id,
            role=UserRole.SUPER_ADMIN.value,
        )
        mapping = (
            await session.execute(
                select(UserTenantMapping).where(
                    UserTenantMapping.user_id == platform_user.id,
                    UserTenantMapping.tenant_id == platform.id,
                )
            )
        ).scalar_one()
        mapping.role = UserRole.SUPER_ADMIN.value
        mapping.default_tenant = True
        mapping.status = "active"
        mapping.is_active = True

        await session.commit()
        print(
            f"Super admin ready: {_SUPER_ADMIN_EMAIL} on platform tenant "
            f"(user_id={platform_user.id}, tenant_id={platform.id}). "
            "Log in and select 'LedgerLink Platform' if prompted."
        )


if __name__ == "__main__":
    asyncio.run(seed_super_admin())
