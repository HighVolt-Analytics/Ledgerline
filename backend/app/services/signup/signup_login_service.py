"""Mint app JWT after signup wizard completes."""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.tenant import Tenant
from app.models.user import User
from app.services.auth.auth_service import create_access_token, create_refresh_token
from app.services.auth.auth_session_service import new_jti, register_refresh_session
from app.services.signup.signup_fulfillment_service import fulfill_signup_tenant
from app.services.signup.signup_session_service import SignupSession, delete_signup_session
from app.tenant_settings import tenant_onboarding_completed


async def mint_auth_for_provisioned_tenant(
    session: AsyncSession,
    *,
    tenant_id: str | uuid.UUID,
    email: str,
) -> dict:
    """Mint session tokens after Stripe webhook has provisioned the tenant."""
    tid = tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))
    tenant = await session.get(Tenant, tid)
    if not tenant:
        raise HTTPException(404, "Organisation not found")

    normalized_email = email.lower().strip()
    user = (
        await session.execute(
            select(User).where(User.tenant_id == tid, User.email == normalized_email)
        )
    ).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(404, "User account not found for this organisation")

    settings = get_settings()
    role = user.role.value
    jti = new_jti()
    access = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        email=user.email,
        role=role,
    )
    refresh = create_refresh_token(
        user_id=user.id,
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        email=user.email,
        role=role,
        jti=jti,
    )
    await register_refresh_session(
        jti=jti,
        user_id=user.id,
        tenant_id=tenant.id,
        ttl_days=settings.refresh_token_expire_days,
    )
    return {
        "access_token": access,
        "refresh_token": refresh,
        "redirect_to": "/settings",
        "user": _user_payload(user, tenant),
    }


async def mint_signup_session_auth(
    session: AsyncSession,
    *,
    signup: SignupSession,
) -> dict:
    tenant, user = await fulfill_signup_tenant(session, signup=signup)
    role = user.role.value
    settings = get_settings()
    jti = new_jti()
    access = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        email=user.email,
        role=role,
    )
    refresh = create_refresh_token(
        user_id=user.id,
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        email=user.email,
        role=role,
        jti=jti,
    )
    await register_refresh_session(
        jti=jti,
        user_id=user.id,
        tenant_id=tenant.id,
        ttl_days=settings.refresh_token_expire_days,
    )
    await delete_signup_session(signup.session_id)
    return {
        "access_token": access,
        "refresh_token": refresh,
        "redirect_to": "/settings",
        "user": _user_payload(user, tenant),
    }


def _user_payload(user: User, tenant: Tenant) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role.value,
        "tenant_id": str(tenant.id),
        "tenant_name": tenant.name,
        "tenant_slug": tenant.slug,
        "onboarding_completed": tenant_onboarding_completed(tenant),
    }
