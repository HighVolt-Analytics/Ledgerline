"""Optional background Xero sync — disabled unless XERO_BACKGROUND_SYNC_ENABLED=true."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_factory
from app.models.accounting_integration import AccountingIntegration, AccountingProvider
from app.models.accounting_sync_job import (
    JOB_STATUS_PENDING,
    JOB_TYPE_CONTACTS,
    JOB_TYPE_RECONCILE,
    JOB_TYPE_SETTINGS,
    AccountingSyncJob,
)
from app.services.integration.xero.xero_reconcile_service import reconcile_pending
from app.services.integration.xero.xero_sync_service import sync_contacts, sync_settings
from app.tenant_rls import apply_rls_session_context
from app.utils.logger import get_logger

logger = get_logger(__name__)

_POLL_SECONDS = 3600
_task: asyncio.Task[Any] | None = None


async def _process_pending_jobs() -> None:
    settings = get_settings()
    if not settings.xero_background_sync_enabled:
        return
    async with async_session_factory() as db:
        rows = list(
            (
                await db.execute(
                    select(AccountingSyncJob)
                    .where(
                        AccountingSyncJob.provider == AccountingProvider.XERO.value,
                        AccountingSyncJob.status == JOB_STATUS_PENDING,
                        AccountingSyncJob.trigger_type.in_(["webhook", "scheduled"]),
                    )
                    .order_by(AccountingSyncJob.id.asc())
                    .limit(20)
                )
            ).scalars()
        )
        for job in rows:
            await apply_rls_session_context(db, job.tenant_id)
            try:
                if job.job_type == JOB_TYPE_RECONCILE:
                    await reconcile_pending(
                        db,
                        tenant_id=job.tenant_id,
                        trigger_type=job.trigger_type or "scheduled",
                    )
                elif job.job_type == JOB_TYPE_SETTINGS:
                    await sync_settings(db, job.tenant_id)
                elif job.job_type == JOB_TYPE_CONTACTS:
                    await sync_contacts(db, job.tenant_id)
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.warning(
                    "xero_background_job_failed",
                    job_id=job.id,
                    error=str(exc),
                )


async def _enqueue_scheduled_syncs() -> None:
    settings = get_settings()
    if not settings.xero_background_sync_enabled:
        return
    from app.services.integration.xero.xero_sync_job_service import enqueue_sync_job

    async with async_session_factory() as db:
        integrations = list(
            (
                await db.execute(
                    select(AccountingIntegration).where(
                        AccountingIntegration.provider == AccountingProvider.XERO.value,
                        AccountingIntegration.status == "connected",
                    )
                )
            ).scalars()
        )
        for integration in integrations:
            await apply_rls_session_context(db, integration.tenant_id)
            await enqueue_sync_job(
                db,
                tenant_id=integration.tenant_id,
                job_type=JOB_TYPE_SETTINGS,
                direction="inbound",
                entity_type="settings",
                trigger_type="scheduled",
            )
            await enqueue_sync_job(
                db,
                tenant_id=integration.tenant_id,
                job_type=JOB_TYPE_CONTACTS,
                direction="inbound",
                entity_type="contact",
                trigger_type="scheduled",
            )
            await enqueue_sync_job(
                db,
                tenant_id=integration.tenant_id,
                job_type=JOB_TYPE_RECONCILE,
                direction="inbound",
                entity_type="invoice",
                trigger_type="scheduled",
            )
        await db.commit()


async def _loop() -> None:
    while True:
        try:
            await _enqueue_scheduled_syncs()
            await _process_pending_jobs()
        except Exception as exc:
            logger.error("xero_background_sync_loop_failed", error=str(exc))
        await asyncio.sleep(_POLL_SECONDS)


def start_xero_background_sync() -> asyncio.Task[Any] | None:
    global _task
    if not get_settings().xero_background_sync_enabled:
        logger.info("xero_background_sync_skipped", reason="disabled")
        return None
    if _task and not _task.done():
        return _task
    _task = asyncio.create_task(_loop(), name="xero-background-sync")
    logger.info("xero_background_sync_started")
    return _task


async def stop_xero_background_sync() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
    logger.info("xero_background_sync_stopped")
