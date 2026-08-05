"""Tenant member listing, role changes, and invite lifecycle."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_account import AuthAccount
from app.models.tenant import Tenant
from app.models.tenant_member_invite import TenantMemberInvite
from app.models.user import User
from app.models.user_tenant_mapping import UserTenantMapping
from app.services.auth.auth_service import hash_password
from app.services.auth.membership_service import ensure_membership
from app.services.shared.public_app_url import build_public_app_path
from app.tenant_rls import (
    apply_platform_lookup_session,
    apply_rls_session_context,
    clear_platform_lookup_session,
)
from app.tenant_roles import TenantRole, normalize_tenant_role, tenant_role_to_user_role


@dataclass(frozen=True)
class TenantMemberRow:
    user_id: int
    email: str
    full_name: str
    role: str
    status: str
    is_active: bool


@dataclass(frozen=True)
class PendingInviteRow:
    id: int
    email: str
    full_name: str
    role: str
    expires_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class InviteCreated:
    invite_id: int
    email: str
    accept_url: str
    expires_at: datetime


@dataclass(frozen=True)
class InvitePreview:
    email: str
    full_name: str
    role: str
    tenant_name: str
    tenant_slug: str
    expired: bool
    accepted: bool


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _require_role_slug(raw: str) -> str:
    role = normalize_tenant_role(raw)
    if role is None:
        raise HTTPException(400, f"Invalid role: {raw}")
    return role.value


async def count_active_seats(session: AsyncSession, *, tenant_id: uuid.UUID) -> int:
    """Active members plus pending (unexpired) invites."""
    now = _utc_now()
    member_count = (
        await session.execute(
            select(func.count())
            .select_from(UserTenantMapping)
            .where(
                UserTenantMapping.tenant_id == tenant_id,
                UserTenantMapping.is_active.is_(True),
                UserTenantMapping.status == "active",
            )
        )
    ).scalar_one()
    pending_count = (
        await session.execute(
            select(func.count())
            .select_from(TenantMemberInvite)
            .where(
                TenantMemberInvite.tenant_id == tenant_id,
                TenantMemberInvite.accepted_at.is_(None),
                TenantMemberInvite.expires_at > now,
            )
        )
    ).scalar_one()
    return int(member_count or 0) + int(pending_count or 0)


async def _count_active_admins(session: AsyncSession, *, tenant_id: uuid.UUID) -> int:
    count = (
        await session.execute(
            select(func.count())
            .select_from(UserTenantMapping)
            .where(
                UserTenantMapping.tenant_id == tenant_id,
                UserTenantMapping.role == TenantRole.ADMIN.value,
                UserTenantMapping.is_active.is_(True),
                UserTenantMapping.status == "active",
            )
        )
    ).scalar_one()
    return int(count or 0)


async def _get_active_mapping(
    session: AsyncSession, *, user_id: int, tenant_id: uuid.UUID
) -> UserTenantMapping | None:
    return (
        await session.execute(
            select(UserTenantMapping).where(
                UserTenantMapping.user_id == user_id,
                UserTenantMapping.tenant_id == tenant_id,
                UserTenantMapping.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()


async def _get_mapping(
    session: AsyncSession, *, user_id: int, tenant_id: uuid.UUID
) -> UserTenantMapping | None:
    return (
        await session.execute(
            select(UserTenantMapping).where(
                UserTenantMapping.user_id == user_id,
                UserTenantMapping.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()


async def _guard_last_admin(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    mapping: UserTenantMapping,
    new_role: str | None = None,
) -> None:
    if mapping.role != TenantRole.ADMIN.value:
        return
    if new_role == TenantRole.ADMIN.value:
        return
    if await _count_active_admins(session, tenant_id=tenant_id) <= 1:
        raise HTTPException(400, "Cannot remove or demote the last admin for this tenant")


async def list_tenant_members(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> tuple[list[TenantMemberRow], list[PendingInviteRow]]:
    rows = (
        await session.execute(
            select(User, UserTenantMapping)
            .join(UserTenantMapping, UserTenantMapping.user_id == User.id)
            .where(UserTenantMapping.tenant_id == tenant_id)
            .order_by(User.full_name, User.email)
        )
    ).all()

    members = [
        TenantMemberRow(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=mapping.role,
            status=mapping.status,
            is_active=mapping.is_active and user.is_active,
        )
        for user, mapping in rows
    ]

    now = _utc_now()
    invite_rows = (
        await session.execute(
            select(TenantMemberInvite)
            .where(
                TenantMemberInvite.tenant_id == tenant_id,
                TenantMemberInvite.accepted_at.is_(None),
                TenantMemberInvite.expires_at > now,
            )
            .order_by(TenantMemberInvite.created_at.desc())
        )
    ).scalars().all()

    pending = [
        PendingInviteRow(
            id=row.id,
            email=row.email,
            full_name=row.full_name,
            role=row.role,
            expires_at=row.expires_at,
            created_at=row.created_at,
        )
        for row in invite_rows
    ]
    return members, pending


async def update_member_role(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: int,
    role: str,
) -> TenantMemberRow:
    role_slug = _require_role_slug(role)
    user = await session.get(User, user_id)
    if not user or user.tenant_id != tenant_id:
        raise HTTPException(404, "Member not found")

    mapping = await _get_active_mapping(session, user_id=user_id, tenant_id=tenant_id)
    if not mapping:
        raise HTTPException(404, "Member not found")

    await _guard_last_admin(session, tenant_id=tenant_id, mapping=mapping, new_role=role_slug)

    mapping.role = role_slug
    user.role = tenant_role_to_user_role(role_slug)
    await session.flush()

    return TenantMemberRow(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=mapping.role,
        status=mapping.status,
        is_active=mapping.is_active and user.is_active,
    )


async def deactivate_member(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: int,
) -> None:
    user = await session.get(User, user_id)
    if not user or user.tenant_id != tenant_id:
        raise HTTPException(404, "Member not found")

    mapping = await _get_active_mapping(session, user_id=user_id, tenant_id=tenant_id)
    if not mapping:
        raise HTTPException(404, "Member not found")

    await _guard_last_admin(session, tenant_id=tenant_id, mapping=mapping, new_role="")

    mapping.is_active = False
    mapping.status = "inactive"
    user.is_active = False
    await session.flush()


async def activate_member(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: int,
) -> TenantMemberRow:
    user = await session.get(User, user_id)
    if not user or user.tenant_id != tenant_id:
        raise HTTPException(404, "Member not found")

    mapping = await _get_mapping(session, user_id=user_id, tenant_id=tenant_id)
    if not mapping:
        raise HTTPException(404, "Member not found")

    mapping.is_active = True
    mapping.status = "active"
    user.is_active = True
    await session.flush()

    return TenantMemberRow(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=mapping.role,
        status=mapping.status,
        is_active=mapping.is_active and user.is_active,
    )


async def create_invite(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    email: str,
    full_name: str,
    role: str,
    invited_by_user_id: int | None,
    ttl_days: int = 7,
) -> InviteCreated:
    role_slug = _require_role_slug(role)
    normalized_email = email.strip().lower()
    if not normalized_email:
        raise HTTPException(400, "Email is required")

    tenant = await session.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    existing_user = (
        await session.execute(
            select(User)
            .join(UserTenantMapping, UserTenantMapping.user_id == User.id)
            .where(
                User.email.ilike(normalized_email),
                UserTenantMapping.tenant_id == tenant_id,
                UserTenantMapping.is_active.is_(True),
                UserTenantMapping.status == "active",
            )
        )
    ).scalar_one_or_none()
    if existing_user:
        raise HTTPException(409, "User is already a member of this tenant")

    now = _utc_now()
    pending = (
        await session.execute(
            select(TenantMemberInvite).where(
                TenantMemberInvite.tenant_id == tenant_id,
                TenantMemberInvite.email.ilike(normalized_email),
                TenantMemberInvite.accepted_at.is_(None),
                TenantMemberInvite.expires_at > now,
            )
        )
    ).scalar_one_or_none()
    if pending:
        raise HTTPException(409, "A pending invite already exists for this email")

    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(days=ttl_days)
    invite = TenantMemberInvite(
        tenant_id=tenant_id,
        email=normalized_email,
        full_name=full_name.strip() or normalized_email.split("@")[0],
        role=role_slug,
        invited_by_user_id=invited_by_user_id,
        token_hash=_hash_token(token),
        expires_at=expires_at,
    )
    session.add(invite)
    await session.flush()

    accept_url = build_public_app_path(f"/accept-invite?token={token}")
    return InviteCreated(
        invite_id=invite.id,
        email=normalized_email,
        accept_url=accept_url,
        expires_at=expires_at,
    )


@dataclass(frozen=True)
class RevokedInvite:
    invite_id: int
    email: str
    role: str


async def revoke_invite(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invite_id: int,
) -> RevokedInvite:
    invite = await session.get(TenantMemberInvite, invite_id)
    if not invite or invite.tenant_id != tenant_id:
        raise HTTPException(404, "Invite not found")
    if invite.accepted_at is not None:
        raise HTTPException(400, "Invite has already been accepted")

    revoked = RevokedInvite(invite_id=invite.id, email=invite.email, role=invite.role)
    await session.delete(invite)
    await session.flush()
    return revoked


async def _load_invite_by_token(session: AsyncSession, token: str) -> TenantMemberInvite:
    """Resolve invite by token hash; bypass RLS for cross-tenant public accept links."""
    token_hash = _hash_token(token.strip())
    await apply_platform_lookup_session(session)
    try:
        invite = (
            await session.execute(
                select(TenantMemberInvite).where(TenantMemberInvite.token_hash == token_hash)
            )
        ).scalar_one_or_none()
    finally:
        await clear_platform_lookup_session(session)
    if not invite:
        raise HTTPException(404, "Invite not found")
    return invite


async def preview_invite(session: AsyncSession, *, token: str) -> InvitePreview:
    invite = await _load_invite_by_token(session, token)

    tenant = await session.get(Tenant, invite.tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    now = _utc_now()
    return InvitePreview(
        email=invite.email,
        full_name=invite.full_name,
        role=invite.role,
        tenant_name=tenant.name,
        tenant_slug=tenant.slug,
        expired=_as_utc(invite.expires_at) <= now,
        accepted=invite.accepted_at is not None,
    )


async def accept_invite(
    session: AsyncSession,
    *,
    token: str,
    password: str,
    full_name: str | None = None,
) -> tuple[User, Tenant, str]:
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")

    invite = await _load_invite_by_token(session, token)
    if invite.accepted_at is not None:
        raise HTTPException(410, "Invite already accepted")

    now = _utc_now()
    if _as_utc(invite.expires_at) <= now:
        raise HTTPException(410, "Invite expired")

    await apply_rls_session_context(session, invite.tenant_id)

    tenant = await session.get(Tenant, invite.tenant_id)
    if not tenant or not tenant.is_active:
        raise HTTPException(403, "Tenant is not available")

    existing = (
        await session.execute(
            select(User)
            .join(UserTenantMapping, UserTenantMapping.user_id == User.id)
            .where(
                User.email.ilike(invite.email),
                UserTenantMapping.tenant_id == invite.tenant_id,
                UserTenantMapping.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "You are already a member of this tenant")

    account = (
        await session.execute(
            select(AuthAccount).where(AuthAccount.email.ilike(invite.email))
        )
    ).scalar_one_or_none()
    password_hash = hash_password(password)
    if not account:
        account = AuthAccount(email=invite.email, password_hash=password_hash)
        session.add(account)
        await session.flush()
    else:
        account.password_hash = password_hash

    display_name = (full_name or invite.full_name).strip() or invite.email.split("@")[0]
    user = User(
        tenant_id=invite.tenant_id,
        auth_account_id=account.id,
        email=invite.email,
        password_hash=account.password_hash,
        full_name=display_name,
        role=tenant_role_to_user_role(invite.role),
        is_active=True,
    )
    session.add(user)
    await session.flush()

    mapping = (
        await session.execute(
            select(UserTenantMapping).where(
                UserTenantMapping.user_id == user.id,
                UserTenantMapping.tenant_id == invite.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if mapping:
        mapping.role = invite.role
        mapping.status = "active"
        mapping.is_active = True
    else:
        await ensure_membership(
            session,
            user_id=user.id,
            tenant_id=invite.tenant_id,
            role=invite.role,
        )

    invite.accepted_at = now
    await session.flush()
    return user, tenant, invite.role
