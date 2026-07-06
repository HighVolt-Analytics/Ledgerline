"""Super-admin portal embed login — token exchange without OTP."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.auth_account import AuthAccount
from app.models.tenant import Tenant
from app.models.user import SUPER_ADMIN_ROLE, User
from app.services.auth.membership_enumeration import (
    filter_switchable_memberships,
    list_memberships_for_auth_account,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PortalEmbedLoginTarget:
    user: User
    tenant: Tenant
    role: str


def _embed_feature_configured(settings: Settings) -> bool:
    return bool(
        settings.super_admin_portal_embed_token.strip()
        and settings.super_admin_portal_embed_email.strip()
    )


def _allowed_origins(settings: Settings) -> list[str]:
    raw = settings.super_admin_portal_embed_allowed_origins.strip()
    if not raw:
        return []
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]


def _validate_origin(settings: Settings, origin: str | None) -> None:
    allowed = _allowed_origins(settings)
    if not allowed:
        return
    if not origin:
        raise HTTPException(403, "Origin not allowed")
    normalized = origin.strip().rstrip("/")
    if normalized not in allowed:
        raise HTTPException(403, "Origin not allowed")


def validate_embed_access_token(settings: Settings, access_token: str) -> None:
    if not _embed_feature_configured(settings):
        raise HTTPException(503, "Portal embed login is not configured")
    expected = settings.super_admin_portal_embed_token.strip()
    provided = access_token.strip()
    if not provided or not secrets.compare_digest(provided, expected):
        logger.info("portal_embed_login_failed", reason="invalid_token")
        raise HTTPException(401, "Invalid access token")


async def resolve_portal_embed_login_target(
    db: AsyncSession,
    *,
    settings: Settings,
) -> PortalEmbedLoginTarget:
    email = settings.super_admin_portal_embed_email.lower().strip()
    account = (
        await db.execute(select(AuthAccount).where(AuthAccount.email.ilike(email)))
    ).scalar_one_or_none()
    if not account or account.is_blocked:
        logger.info("portal_embed_login_failed", email=email, reason="account_not_found")
        raise HTTPException(403, "Super admin account unavailable")

    memberships = filter_switchable_memberships(
        await list_memberships_for_auth_account(
            db,
            auth_account_id=account.id,
            log_source="portal_embed",
        )
    )
    platform_match = next(
        (m for m in memberships if m.is_platform and m.role == SUPER_ADMIN_ROLE),
        None,
    )
    if not platform_match:
        logger.info(
            "portal_embed_login_failed",
            email=email,
            auth_account_id=account.id,
            reason="no_platform_super_admin_membership",
        )
        raise HTTPException(403, "Super admin account unavailable")

    user = await db.get(User, platform_match.user_id)
    tenant = await db.get(Tenant, platform_match.tenant_id)
    if not user or not tenant or not user.is_active:
        logger.info(
            "portal_embed_login_failed",
            email=email,
            reason="inactive_super_admin",
        )
        raise HTTPException(403, "Super admin account unavailable")
    if not tenant.is_active or tenant.lifecycle_status != "active":
        raise HTTPException(403, "Platform tenant unavailable")

    return PortalEmbedLoginTarget(user=user, tenant=tenant, role=platform_match.role)


def check_portal_embed_request(
    settings: Settings,
    *,
    access_token: str,
    origin: str | None,
) -> None:
    validate_embed_access_token(settings, access_token)
    _validate_origin(settings, origin)
