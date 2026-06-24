"""Poll all connected mailboxes and ingest attachments."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connected_mailbox import ConnectedMailbox
from app.models.tenant import Tenant
from app.services.mailbox_inbox_poll import poll_connected_mailbox
from app.services.mailbox_oauth_service import resolve_mailbox_access_token
from app.services.tenant_context_service import get_or_create_default_tenant, sync_env_mailbox
from app.services.pipeline import EmailIngestResult, ingest_email_attachments
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def poll_all_and_ingest(
    session: AsyncSession,
    *,
    tenant_id: int | None = None,
) -> EmailIngestResult:
    """Poll active connected mailboxes; optionally scoped to one tenant."""
    merged = EmailIngestResult()
    if tenant_id is None:
        default_org = await get_or_create_default_tenant(session)
        await sync_env_mailbox(session, default_org.id)

    stmt = select(ConnectedMailbox).where(ConnectedMailbox.is_active.is_(True))
    if tenant_id is not None:
        stmt = stmt.where(ConnectedMailbox.tenant_id == tenant_id)
    mailboxes = (await session.execute(stmt)).scalars().all()

    for mb in mailboxes:
        if not mb.is_pollable:
            logger.info(
                "poll_mailbox_skipped",
                mailbox=mb.email,
                auth_type=mb.auth_type,
                connection_status=mb.connection_status,
            )
            continue

        org = await session.get(Tenant, mb.tenant_id)
        if not org:
            continue

        try:
            access_token = await resolve_mailbox_access_token(session, mb)
        except Exception as exc:
            logger.warning("poll_mailbox_token_failed", mailbox=mb.email, error=str(exc))
            continue

        emails = poll_connected_mailbox(
            mb.email,
            access_token=access_token,
            mail_provider=mb.mail_provider,
        )
        result = await ingest_email_attachments(
            session,
            emails,
            tenant_id=mb.tenant_id,
            tenant_slug=org.slug,
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
    tenant_id: int,
) -> EmailIngestResult:
    """Poll a single connected mailbox and ingest attachments."""
    mb = await session.get(ConnectedMailbox, mailbox_id)
    if not mb or mb.tenant_id != tenant_id or not mb.is_active:
        raise ValueError("Mailbox not found or inactive")
    if not mb.is_pollable:
        raise ValueError("Mailbox is not connected — complete OAuth to authorize access")

    org = await session.get(Tenant, mb.tenant_id)
    if not org:
        raise ValueError("Tenant not found")

    access_token = await resolve_mailbox_access_token(session, mb)
    emails = poll_connected_mailbox(
        mb.email,
        access_token=access_token,
        mail_provider=mb.mail_provider,
    )
    result = await ingest_email_attachments(
        session,
        emails,
        tenant_id=mb.tenant_id,
        tenant_slug=org.slug,
        connected_mailbox_id=mb.id,
    )
    mb.last_poll_at = datetime.now(timezone.utc)
    return result
