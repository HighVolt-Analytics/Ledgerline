"""Poll all connected mailboxes and ingest attachments."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connected_mailbox import ConnectedMailbox
from app.models.organisation import Organisation
from app.services.email_ingestion import poll_inbox
from app.services.org_context import get_or_create_default_org, sync_env_mailbox
from app.services.pipeline import EmailIngestResult, ingest_email_attachments


async def poll_all_and_ingest(session: AsyncSession) -> EmailIngestResult:
    """Poll every active connected mailbox for the organisation(s)."""
    merged = EmailIngestResult()
    default_org = await get_or_create_default_org(session)
    await sync_env_mailbox(session, default_org.id)

    mailboxes = (
        await session.execute(
            select(ConnectedMailbox).where(ConnectedMailbox.is_active.is_(True))
        )
    ).scalars().all()

    for mb in mailboxes:
        org = await session.get(Organisation, mb.org_id)
        if not org:
            continue
        emails = poll_inbox(mb.email)
        result = await ingest_email_attachments(
            session,
            emails,
            org_id=mb.org_id,
            org_slug=org.slug,
            connected_mailbox_id=mb.id,
        )
        mb.last_poll_at = datetime.now(timezone.utc)
        merged.ingested_count += result.ingested_count
        merged.message_ids.extend(result.message_ids)
        merged.preskip_exceptions.update(result.preskip_exceptions)

    return merged


async def poll_mailbox_and_ingest(
    session: AsyncSession,
    *,
    mailbox_id: int,
    org_id: int,
) -> EmailIngestResult:
    """Poll a single connected mailbox and ingest attachments."""
    mb = await session.get(ConnectedMailbox, mailbox_id)
    if not mb or mb.org_id != org_id or not mb.is_active:
        raise ValueError("Mailbox not found or inactive")

    org = await session.get(Organisation, mb.org_id)
    if not org:
        raise ValueError("Organisation not found")

    emails = poll_inbox(mb.email)
    result = await ingest_email_attachments(
        session,
        emails,
        org_id=mb.org_id,
        org_slug=org.slug,
        connected_mailbox_id=mb.id,
    )
    mb.last_poll_at = datetime.now(timezone.utc)
    return result
