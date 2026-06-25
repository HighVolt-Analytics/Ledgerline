"""Historical mailbox import from a user-selected date range."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import db_session_with_rls, platform_lookup_session
from app.tenant_scoped import get_for_tenant
from app.models.connected_mailbox import ConnectedMailbox
from app.models.invoice import Invoice
from app.models.mailbox_sync_job import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    MailboxSyncJob,
)
from app.models.tenant import Tenant
from app.services.audit_service import log_event
from app.services.email_ingestion import fetch_historical_inbox
from app.services.graph_mail_folders import finalize_graph_messages, folder_moves_enabled
from app.services.mailbox_oauth_service import resolve_mailbox_access_token
from app.services.pipeline import ingest_email_attachments
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def _known_message_ids(session: AsyncSession, *, tenant_id: int) -> frozenset[str]:
    rows = (
        await session.execute(
            select(Invoice.email_message_id).where(
                Invoice.tenant_id == tenant_id,
                Invoice.email_message_id.isnot(None),
            )
        )
    ).scalars().all()
    return frozenset(str(row) for row in rows if row)


async def _running_job_for_mailbox(
    session: AsyncSession,
    *,
    mailbox_id: int,
    tenant_id: int,
) -> MailboxSyncJob | None:
    return (
        await session.execute(
            select(MailboxSyncJob).where(
                MailboxSyncJob.mailbox_id == mailbox_id,
                MailboxSyncJob.tenant_id == tenant_id,
                MailboxSyncJob.status.in_((STATUS_QUEUED, STATUS_RUNNING)),
            )
        )
    ).scalar_one_or_none()


def validate_backfill_dates(from_day: date, to_day: date) -> None:
    if to_day < from_day:
        raise ValueError("End date must be on or after start date")
    max_days = get_settings().graph_backfill_max_days
    span = (to_day - from_day).days + 1
    if span > max_days:
        raise ValueError(f"Date range cannot exceed {max_days} days")


async def create_mailbox_backfill_job(
    session: AsyncSession,
    *,
    tenant_id: int,
    mailbox_id: int,
    from_day: date,
    to_day: date,
    mark_processed: bool,
    requested_by_user_id: int | None = None,
) -> MailboxSyncJob:
    validate_backfill_dates(from_day, to_day)

    mb = await session.get(ConnectedMailbox, mailbox_id)
    if not mb or mb.tenant_id != tenant_id:
        raise ValueError("Mailbox not found")
    if not mb.is_active:
        raise ValueError("Mailbox is paused")
    if not mb.is_pollable:
        raise ValueError("Mailbox is not connected — sign in with Microsoft to authorize access")

    existing = await _running_job_for_mailbox(session, mailbox_id=mailbox_id, tenant_id=tenant_id)
    if existing is not None:
        raise ValueError("A historical import is already running for this mailbox")

    job = MailboxSyncJob(
        tenant_id=tenant_id,
        mailbox_id=mailbox_id,
        from_date=from_day,
        to_date=to_day,
        mark_processed=mark_processed,
        status=STATUS_QUEUED,
        requested_by_user_id=requested_by_user_id,
    )
    session.add(job)
    await session.flush()

    await log_event(
        session,
        "mailbox_backfill_requested",
        tenant_id=tenant_id,
        detail={
            "job_id": job.id,
            "mailbox_id": mailbox_id,
            "mailbox_email": mb.email,
            "from_date": from_day.isoformat(),
            "to_date": to_day.isoformat(),
            "mark_processed": mark_processed,
        },
    )
    await session.flush()
    return job


async def run_mailbox_backfill_job(
    job_id: int,
    *,
    tenant_id: uuid.UUID | None = None,
) -> MailboxSyncJob:
    """Execute one historical import job (Celery / inline worker entry)."""
    from app.tenant_scoped import coerce_tenant_uuid

    resolved_tid = coerce_tenant_uuid(tenant_id)
    async with platform_lookup_session() as lookup:
        job_peek = await lookup.get(MailboxSyncJob, job_id)
        if job_peek is None:
            raise ValueError("Import job not found")
        if resolved_tid is not None and job_peek.tenant_id != resolved_tid:
            raise ValueError("Import job not found")
        resolved_tid = job_peek.tenant_id

    async with db_session_with_rls(resolved_tid) as session:
        job = await get_for_tenant(session, MailboxSyncJob, job_id, resolved_tid)
        if job is None:
            raise ValueError("Import job not found")

        mb = await get_for_tenant(session, ConnectedMailbox, job.mailbox_id, resolved_tid)
        org = await session.get(Tenant, job.tenant_id)
        if not mb or not org or mb.tenant_id != job.tenant_id:
            job.status = STATUS_FAILED
            job.error_message = "Mailbox or organisation not found"
            job.finished_at = datetime.now(timezone.utc)
            await session.commit()
            return job

        job.status = STATUS_RUNNING
        job.started_at = datetime.now(timezone.utc)
        job.error_message = None
        await session.commit()

        message_ids: list[str] = []
        preskip: dict[str, str] = {}

        try:
            access_token = await resolve_mailbox_access_token(session, mb)
            known_ids = await _known_message_ids(session, tenant_id=job.tenant_id)
            emails = fetch_historical_inbox(
                mb.email,
                from_day=job.from_date,
                to_day=job.to_date,
                access_token=access_token,
                max_messages=get_settings().graph_backfill_max_messages,
            )
            job.messages_scanned = len(emails)

            if emails:
                ingest_result = await ingest_email_attachments(
                    session,
                    emails,
                    tenant_id=job.tenant_id,
                    tenant_slug=org.slug,
                    connected_mailbox_id=mb.id,
                    mark_processed=job.mark_processed,
                    mark_processed_only_if_ingested=True,
                    known_message_ids=known_ids,
                )
                job.attachments_ingested = ingest_result.ingested_count
                message_ids = ingest_result.message_ids
                preskip = ingest_result.preskip_exceptions
                job.messages_skipped = sum(
                    1
                    for mid in message_ids
                    if preskip.get(mid) == "message_already_imported"
                )
            else:
                job.attachments_ingested = 0
                job.messages_skipped = 0

            mb.last_poll_at = datetime.now(timezone.utc)
            await session.commit()

            if job.attachments_ingested:
                from app.workers.tasks import _fetch_pending_ids, _process_pending

                job.invoices_processed = await _process_pending(
                    await _fetch_pending_ids(tenant_id=job.tenant_id),
                    tenant_id=job.tenant_id,
                )
                await session.commit()

            if message_ids and job.mark_processed and folder_moves_enabled():
                moved = await finalize_graph_messages(
                    session,
                    message_ids,
                    tenant_id=job.tenant_id,
                    preskip_exceptions=preskip,
                )
                logger.info(
                    "backfill_messages_finalized",
                    job_id=job.id,
                    moved=moved,
                    total=len(message_ids),
                )
                await session.commit()

            job.status = STATUS_COMPLETED
            job.finished_at = datetime.now(timezone.utc)
            await log_event(
                session,
                "mailbox_backfill_completed",
                tenant_id=job.tenant_id,
                detail={
                    "job_id": job.id,
                    "mailbox_id": job.mailbox_id,
                    "messages_scanned": job.messages_scanned,
                    "attachments_ingested": job.attachments_ingested,
                    "invoices_processed": job.invoices_processed,
                },
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            job = await get_for_tenant(session, MailboxSyncJob, job_id, resolved_tid)
            if job:
                job.status = STATUS_FAILED
                job.error_message = str(exc)[:2000]
                job.finished_at = datetime.now(timezone.utc)
                await log_event(
                    session,
                    "mailbox_backfill_failed",
                    tenant_id=job.tenant_id,
                    detail={"job_id": job.id, "error": job.error_message},
                )
                await session.commit()
            logger.exception("mailbox_backfill_failed", job_id=job_id)
            raise

        await session.refresh(job)
        return job


async def get_mailbox_backfill_job(
    session: AsyncSession,
    *,
    job_id: int,
    tenant_id: int,
) -> MailboxSyncJob:
    job = await session.get(MailboxSyncJob, job_id)
    if not job or job.tenant_id != tenant_id:
        raise ValueError("Import job not found")
    return job
