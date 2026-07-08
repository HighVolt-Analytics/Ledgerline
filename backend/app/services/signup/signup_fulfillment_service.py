"""Provision tenant + admin user after signup payment/plan selection."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_account import AuthAccount
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services.auth.auth_service import hash_password
from app.services.auth.membership_service import ensure_membership
from app.services.credit_catalog import PLAN_FREE, PLAN_STUDIO
from app.services.credit_service import ensure_tenant_billing, upgrade_to_studio
from app.services.rule_book.rule_book_config_repository import ensure_default_config
from app.services.signup.signup_session_service import SignupSession
from app.services.tenant.platform_service import _seed_modules
from app.tenant_roles import TenantRole
from app.tenant_settings import DEFAULT_COUNTRY, build_tenant_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_OAUTH_ONLY_PASSWORD_SALT = "ledgerlink-oauth-only-no-password"
_PLACEHOLDER_HASH: str | None = None


def oauth_placeholder_password_hash() -> str:
    global _PLACEHOLDER_HASH
    if _PLACEHOLDER_HASH is None:
        _PLACEHOLDER_HASH = hash_password(_OAUTH_ONLY_PASSWORD_SALT)
    return _PLACEHOLDER_HASH


def slugify_organization_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:64] or "org"


async def ensure_unique_tenant_slug(session: AsyncSession, base_slug: str) -> str:
    slug = base_slug[:64]
    attempt = 0
    while True:
        candidate = slug if attempt == 0 else f"{slug[:58]}-{attempt}"
        taken = (
            await session.execute(select(Tenant).where(Tenant.slug == candidate))
        ).scalar_one_or_none()
        if not taken:
            return candidate
        attempt += 1
        if attempt > 100:
            raise ValueError("Could not allocate a unique tenant slug")


async def ensure_pending_auth_account(
    session: AsyncSession,
    *,
    email: str,
    password_hash: str,
) -> AuthAccount:
    normalized = email.lower().strip()
    account = (
        await session.execute(select(AuthAccount).where(AuthAccount.email == normalized))
    ).scalar_one_or_none()
    if account:
        if account.password_hash == oauth_placeholder_password_hash():
            account.password_hash = password_hash
        return account
    account = AuthAccount(email=normalized, password_hash=password_hash)
    session.add(account)
    await session.flush()
    return account


async def fulfill_signup_tenant(
    session: AsyncSession,
    *,
    signup: SignupSession,
) -> tuple[Tenant, User]:
    if not signup.organization_name or not signup.auth_account_id:
        raise ValueError("Signup session is incomplete")

    account = await session.get(AuthAccount, signup.auth_account_id)
    if not account:
        raise ValueError("Auth account not found")

    if signup.tenant_id:
        tenant = await session.get(Tenant, uuid.UUID(signup.tenant_id))
        user = (
            await session.execute(
                select(User).where(
                    User.tenant_id == tenant.id,
                    User.auth_account_id == account.id,
                )
            )
        ).scalar_one_or_none()
        if tenant and user:
            return tenant, user

    base_slug = signup.organization_slug or slugify_organization_name(signup.organization_name)
    slug = await ensure_unique_tenant_slug(session, base_slug)
    plan = (signup.plan or PLAN_FREE).strip().lower()

    settings_json = build_tenant_settings(
        country=(signup.country or DEFAULT_COUNTRY).strip().upper(),
        onboarding_completed=True,
    )
    settings_json["setup_checklist_complete"] = False

    tenant = Tenant(
        name=signup.organization_name.strip(),
        slug=slug,
        is_active=True,
        is_platform=False,
        lifecycle_status="active",
        settings_json=settings_json,
    )
    session.add(tenant)
    await session.flush()

    await _seed_modules(session, tenant.id)
    await ensure_default_config(session, tenant.id)
    await ensure_tenant_billing(session, tenant.id, plan=PLAN_FREE)
    if plan == PLAN_STUDIO:
        await upgrade_to_studio(session, tenant.id)

    password_hash = signup.password_hash or account.password_hash
    display_name = signup.full_name.strip() or signup.email.split("@")[0]
    user = User(
        tenant_id=tenant.id,
        auth_account_id=account.id,
        email=signup.email,
        password_hash=password_hash,
        full_name=display_name,
        role=UserRole.ADMIN,
        is_active=True,
    )
    session.add(user)
    await session.flush()

    await ensure_membership(
        session,
        user_id=user.id,
        tenant_id=tenant.id,
        role=TenantRole.ADMIN.value,
        default_tenant=True,
    )
    await session.flush()

    logger.info(
        "signup_tenant_provisioned",
        tenant_id=str(tenant.id),
        tenant_slug=tenant.slug,
        plan=plan,
        email=signup.email,
    )
    return tenant, user
