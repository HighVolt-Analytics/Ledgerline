"""Resolve organisation context for API and workers."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.connected_mailbox import ConnectedMailbox
from app.models.organisation import Organisation
from app.services.mailbox_oauth_service import mark_application_mailbox


async def get_org_by_id(session: AsyncSession, org_id: int) -> Organisation | None:
    return await session.get(Organisation, org_id)


async def get_org_slug(session: AsyncSession, org_id: int) -> str:
    """Resolve tenant slug from org_id (source of truth for vault paths and auth)."""
    org = await get_org_by_id(session, org_id)
    if org and org.slug.strip():
        return org.slug
    return get_settings().default_org_slug


async def get_or_create_default_org(session: AsyncSession) -> Organisation:
    settings = get_settings()
    row = (
        await session.execute(
            select(Organisation).where(Organisation.slug == settings.default_org_slug)
        )
    ).scalar_one_or_none()
    if row:
        return row
    org = Organisation(name=settings.default_org_name, slug=settings.default_org_slug)
    session.add(org)
    await session.flush()
    return org


async def ensure_connected_mailbox(
    session: AsyncSession,
    org_id: int,
    email: str,
    *,
    display_name: str | None = None,
) -> None:
    """Idempotently add an Outlook mailbox for Graph polling."""
    mailbox = email.strip().lower()
    if not mailbox:
        return
    existing = (
        await session.execute(
            select(ConnectedMailbox).where(
                ConnectedMailbox.org_id == org_id,
                ConnectedMailbox.email == mailbox,
            )
        )
    ).scalar_one_or_none()
    if existing:
        if existing.auth_type != "delegated":
            mark_application_mailbox(existing)
        return
    row = ConnectedMailbox(
        org_id=org_id,
        email=mailbox,
        display_name=display_name or mailbox,
        is_active=True,
    )
    mark_application_mailbox(row)
    session.add(row)
    await session.flush()


async def sync_env_mailbox(session: AsyncSession, org_id: int) -> None:
    """Ensure GRAPH_MAILBOX from env exists as a connected mailbox."""
    mailbox = get_settings().graph_mailbox.strip().lower()
    if not mailbox:
        return
    await ensure_connected_mailbox(session, org_id, mailbox)
