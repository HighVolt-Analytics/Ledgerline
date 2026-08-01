"""Resolve tenant context for API and workers."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.connected_mailbox import ConnectedMailbox
from app.models.tenant import Tenant
from app.services.ingest.mailbox_oauth_service import mark_application_mailbox


async def get_tenant_by_id(session: AsyncSession, tenant_id: uuid.UUID) -> Tenant | None:
    return await session.get(Tenant, tenant_id)


async def get_tenant_slug(session: AsyncSession, tenant_id: uuid.UUID) -> str:
    tenant = await get_tenant_by_id(session, tenant_id)
    if tenant and tenant.slug.strip():
        return tenant.slug
    return get_settings().default_tenant_slug


async def get_or_create_default_tenant(session: AsyncSession) -> Tenant:
    settings = get_settings()
    row = (
        await session.execute(
            select(Tenant).where(Tenant.slug == settings.default_tenant_slug)
        )
    ).scalar_one_or_none()
    if row:
        return row
    tenant = Tenant(name=settings.default_tenant_name, slug=settings.default_tenant_slug)
    session.add(tenant)
    await session.flush()
    return tenant


async def list_active_tenant_ids(session: AsyncSession) -> list[uuid.UUID]:
    rows = (
        await session.execute(
            select(Tenant.id).where(
                Tenant.is_active.is_(True),
                Tenant.lifecycle_status == "active",
            )
        )
    ).scalars().all()
    return list(rows)


async def list_active_tenant_ids_with_mailboxes(
    session: AsyncSession,
) -> list[uuid.UUID]:
    """Active tenants that have at least one active connected mailbox.

    Inline poll cycles must not walk every empty sandbox tenant — that alone
    stretches a 2-minute interval into 5–7 minutes before the real mailbox is hit.
    """
    rows = (
        await session.execute(
            select(Tenant.id)
            .join(ConnectedMailbox, ConnectedMailbox.tenant_id == Tenant.id)
            .where(
                Tenant.is_active.is_(True),
                Tenant.lifecycle_status == "active",
                ConnectedMailbox.is_active.is_(True),
            )
            .distinct()
            .order_by(Tenant.id)
        )
    ).scalars().all()
    return list(rows)


async def ensure_connected_mailbox(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    email: str,
    *,
    display_name: str | None = None,
) -> None:
    mailbox = email.strip().lower()
    if not mailbox:
        return
    existing = (
        await session.execute(
            select(ConnectedMailbox).where(
                ConnectedMailbox.tenant_id == tenant_id,
                ConnectedMailbox.email == mailbox,
            )
        )
    ).scalar_one_or_none()
    if existing:
        if existing.auth_type != "delegated":
            mark_application_mailbox(existing)
        return
    row = ConnectedMailbox(
        tenant_id=tenant_id,
        email=mailbox,
        display_name=display_name or mailbox,
        is_active=True,
    )
    mark_application_mailbox(row)
    session.add(row)
    await session.flush()


async def sync_env_mailbox(session: AsyncSession, tenant_id: int) -> None:
    mailbox = get_settings().graph_mailbox.strip().lower()
    if not mailbox:
        return
    await ensure_connected_mailbox(session, tenant_id, mailbox)
