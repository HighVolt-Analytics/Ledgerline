"""Poll all connected mailboxes and ingest attachments."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connected_mailbox import ConnectedMailbox
from app.models.invoice import Invoice
from app.models.tenant import Tenant
from app.services.ingest.mailbox_inbox_poll import poll_connected_mailbox
from app.services.ingest.mailbox_oauth_service import resolve_mailbox_access_token
from app.services.tenant.tenant_context_service import get_or_create_default_tenant, sync_env_mailbox
from app.services.invoice.pipeline import EmailIngestResult, ingest_email_attachments
from app.tenant_rls import apply_rls_session_context
from app.utils.logger import get_logger

logger = get_logger(__name__)

_RECENT_POLL_LOOKBACK = timedelta(hours=48)


async def known_message_ids(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> frozenset[str]:
    from app.services.ingest.mailbox_message_service import (
        known_terminal_mailbox_message_ids,
    )

    invoice_ids = (
        await session.execute(
            select(Invoice.email_message_id).where(
                Invoice.tenant_id == tenant_id,
                Invoice.email_message_id.isnot(None),
            )
        )
    ).scalars().all()
    mailbox_ids = await known_terminal_mailbox_message_ids(
        session, tenant_id=tenant_id
    )
    return frozenset(str(row) for row in invoice_ids if row) | mailbox_ids


def _poll_since_timestamp(last_poll_at: datetime | None) -> datetime:
    """Look back 48h so read messages skipped by rules can be retried."""
    _ = last_poll_at
    now = datetime.now(timezone.utc)
    return now - _RECENT_POLL_LOOKBACK


async def _poll_mailbox_emails(
    mb: ConnectedMailbox,
    *,
    access_token: str,
    known_ids: frozenset[str],
) -> list:
    since = _poll_since_timestamp(mb.last_poll_at)
    logger.info(
        "poll_mailbox_fetch_started",
        tenant_id=str(mb.tenant_id),
        mailbox_id=mb.id,
        mailbox=mb.email,
        mail_provider=mb.mail_provider,
        since=since.isoformat(),
        known_message_id_count=len(known_ids),
        last_poll_at=mb.last_poll_at.isoformat() if mb.last_poll_at else None,
    )
    emails = await asyncio.to_thread(
        poll_connected_mailbox,
        mb.email,
        access_token=access_token,
        mail_provider=mb.mail_provider,
        since=since,
        known_message_ids=known_ids,
    )
    attachment_count = sum(len(email.attachments) for email in emails)
    logger.info(
        "poll_mailbox_fetch_done",
        tenant_id=str(mb.tenant_id),
        mailbox_id=mb.id,
        mailbox=mb.email,
        email_count=len(emails),
        attachment_count=attachment_count,
        message_ids=[email.message_id for email in emails],
    )
    return emails


async def _recover_poll_session_if_needed(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Rollback only when the session transaction is invalid (e.g. after a DB error)."""
    if session.is_active:
        return
    await session.rollback()
    await apply_rls_session_context(session, tenant_id)


async def _ingest_mailbox(
    session: AsyncSession,
    mb: ConnectedMailbox,
    *,
    known_ids: frozenset[str],
) -> EmailIngestResult:
    org = await session.get(Tenant, mb.tenant_id)
    if not org:
        from app.services.ingest.ingest_skip_service import log_ingest_skip

        await log_ingest_skip(
            session,
            reason="mailbox_org_missing",
            channel="email",
            tenant_id=mb.tenant_id,
            mailbox=mb.email,
        )
        return EmailIngestResult()

    from app.services.credit_service import PlanFeatureBlockedError, assert_can_ingest_via_channel

    try:
        await assert_can_ingest_via_channel(session, mb.tenant_id, channel="email")
    except PlanFeatureBlockedError as exc:
        mb.last_error = str(exc)[:500]
        mb.last_poll_at = datetime.now(timezone.utc)
        logger.warning(
            "poll_mailbox_plan_blocked",
            mailbox=mb.email,
            tenant_id=str(mb.tenant_id),
            error=str(exc),
        )
        from app.services.ingest.ingest_skip_service import log_ingest_skip

        await log_ingest_skip(
            session,
            reason="plan_channel_blocked",
            channel="email",
            tenant_id=mb.tenant_id,
            mailbox=mb.email,
            extra={"error": str(exc)[:500]},
        )
        return EmailIngestResult()

    try:
        access_token = await resolve_mailbox_access_token(session, mb)
    except Exception as exc:
        logger.warning("poll_mailbox_token_failed", mailbox=mb.email, error=str(exc))
        from app.services.ingest.ingest_skip_service import log_ingest_skip

        await log_ingest_skip(
            session,
            reason="mailbox_token_failed",
            channel="email",
            tenant_id=mb.tenant_id,
            mailbox=mb.email,
            exc_type=type(exc).__name__,
            extra={"error": str(exc)[:500]},
        )
        await _recover_poll_session_if_needed(session, mb.tenant_id)
        return EmailIngestResult()

    from app.models.connected_mailbox import MAIL_PROVIDER_GOOGLE
    from app.services.ingest.gmail_oauth_service import gmail_oauth_configured
    from app.services.ingest.graph_client import is_graph_enabled
    from app.services.ingest.ingest_skip_service import log_ingest_skip

    if mb.mail_provider == MAIL_PROVIDER_GOOGLE:
        if not gmail_oauth_configured():
            await log_ingest_skip(
                session,
                reason="gmail_not_configured",
                channel="email",
                tenant_id=mb.tenant_id,
                mailbox=mb.email,
            )
            return EmailIngestResult()
    elif not is_graph_enabled():
        await log_ingest_skip(
            session,
            reason="graph_not_configured",
            channel="email",
            tenant_id=mb.tenant_id,
            mailbox=mb.email,
        )
        return EmailIngestResult()

    try:
        emails = await _poll_mailbox_emails(mb, access_token=access_token, known_ids=known_ids)
        from app.services.ingest.mailbox_message_service import (
            apply_preskip_mailbox_outcomes,
            ensure_pending_for_emails,
        )

        await ensure_pending_for_emails(session, mailbox=mb, emails=emails)
        result = await ingest_email_attachments(
            session,
            emails,
            tenant_id=mb.tenant_id,
            tenant_slug=org.slug,
            connected_mailbox_id=mb.id,
            known_message_ids=known_ids,
            mark_processed_only_if_ingested=True,
        )
        if result.preskip_exceptions:
            await apply_preskip_mailbox_outcomes(
                session,
                connected_mailbox_id=mb.id,
                tenant_id=mb.tenant_id,
                provider=mb.mail_provider,
                preskip_exceptions=result.preskip_exceptions,
                message_graph_ids=result.message_graph_ids,
            )
        mb.last_poll_at = datetime.now(timezone.utc)
        mb.last_error = None
        logger.info(
            "poll_mailbox_ingest_done",
            tenant_id=str(mb.tenant_id),
            mailbox_id=mb.id,
            mailbox=mb.email,
            ingested_count=result.ingested_count,
            fetched_email_count=len(emails),
            skip_count=len(result.preskip_exceptions),
            skip_reasons=dict(result.preskip_exceptions),
        )
        return result
    except Exception as exc:
        error_text = str(exc)[:500]
        lowered = error_text.lower()
        auth_failure = (
            "403" in lowered
            or "401" in lowered
            or "forbidden" in lowered
            or "unauthorized" in lowered
            or "access denied" in lowered
        )
        logger.warning("poll_mailbox_ingest_failed", mailbox=mb.email, error=str(exc))
        from app.services.ingest.ingest_skip_service import log_ingest_skip

        await log_ingest_skip(
            session,
            reason="mailbox_poll_failed",
            channel="email",
            tenant_id=mb.tenant_id,
            mailbox=mb.email,
            exc_type=type(exc).__name__,
            extra={"error": error_text},
        )
        await _recover_poll_session_if_needed(session, mb.tenant_id)
        refreshed = await session.get(ConnectedMailbox, mb.id)
        if refreshed is not None:
            refreshed.last_error = error_text
            if auth_failure:
                from app.models.connected_mailbox import STATUS_ERROR

                refreshed.connection_status = STATUS_ERROR
        return EmailIngestResult()


async def poll_all_and_ingest(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID | None = None,
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

    logger.info(
        "poll_all_mailboxes_started",
        tenant_id=str(tenant_id) if tenant_id else None,
        active_mailbox_count=len(mailboxes),
        pollable_mailbox_count=sum(1 for mb in mailboxes if mb.is_pollable),
        mailbox_emails=[mb.email for mb in mailboxes if mb.is_pollable],
    )

    scoped_tenant_id = tenant_id
    if scoped_tenant_id is None and mailboxes:
        scoped_tenant_id = mailboxes[0].tenant_id
    known_ids = (
        await known_message_ids(session, tenant_id=scoped_tenant_id)
        if scoped_tenant_id is not None
        else frozenset()
    )

    for mb in mailboxes:
        if not mb.is_pollable:
            from app.services.ingest.ingest_skip_service import log_ingest_skip

            logger.info(
                "poll_mailbox_skipped",
                mailbox=mb.email,
                auth_type=mb.auth_type,
                connection_status=mb.connection_status,
            )
            await log_ingest_skip(
                session,
                reason="mailbox_not_pollable",
                channel="email",
                tenant_id=mb.tenant_id,
                mailbox=mb.email,
                extra={
                    "auth_type": mb.auth_type,
                    "connection_status": mb.connection_status,
                },
            )
            continue

        try:
            mb_known_ids = await known_message_ids(session, tenant_id=mb.tenant_id)
            result = await _ingest_mailbox(session, mb, known_ids=mb_known_ids)
        except Exception as exc:
            logger.warning("poll_mailbox_failed", mailbox=mb.email, error=str(exc))
            continue
        merged.ingested_count += result.ingested_count
        merged.message_ids.extend(result.message_ids)
        merged.preskip_exceptions.update(result.preskip_exceptions)
        merged.message_mailbox_emails.update(result.message_mailbox_emails)
        merged.message_graph_ids.update(result.message_graph_ids)
        known_ids = known_ids | mb_known_ids

    logger.info(
        "poll_all_mailboxes_done",
        tenant_id=str(tenant_id) if tenant_id else None,
        ingested_count=merged.ingested_count,
        message_count=len(merged.message_ids),
        skip_count=len(merged.preskip_exceptions),
        skip_reasons=dict(merged.preskip_exceptions),
    )

    return merged


async def poll_mailbox_and_ingest(
    session: AsyncSession,
    *,
    mailbox_id: int,
    tenant_id: uuid.UUID,
) -> EmailIngestResult:
    """Poll a single connected mailbox and ingest attachments."""
    mb = await session.get(ConnectedMailbox, mailbox_id)
    if not mb or mb.tenant_id != tenant_id or not mb.is_active:
        raise ValueError("Mailbox not found or inactive")
    if not mb.is_pollable:
        raise ValueError("Mailbox is not connected — complete OAuth to authorize access")

    known_ids = await known_message_ids(session, tenant_id=mb.tenant_id)
    return await _ingest_mailbox(session, mb, known_ids=known_ids)
