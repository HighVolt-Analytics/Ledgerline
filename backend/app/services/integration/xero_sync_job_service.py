"""Enqueue and track manual Xero sync jobs."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting_sync_job import (
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    AccountingSyncJob,
)
from app.models.accounting_integration import AccountingProvider


def _payload_hash(job_type: str) -> str:
    return hashlib.sha256(job_type.encode("utf-8")).hexdigest()


async def enqueue_sync_job(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    job_type: str,
    provider: str = AccountingProvider.XERO.value,
) -> AccountingSyncJob:
    job = AccountingSyncJob(
        tenant_id=tenant_id,
        provider=provider,
        job_type=job_type,
        status=JOB_STATUS_PENDING,
        payload_hash=_payload_hash(job_type),
    )
    db.add(job)
    await db.flush()
    return job


async def mark_job_running(db: AsyncSession, job: AccountingSyncJob) -> None:
    now = datetime.now(timezone.utc)
    job.status = JOB_STATUS_RUNNING
    job.attempts = int(job.attempts or 0) + 1
    job.started_at = now
    job.error_code = None
    job.error_message = None
    await db.flush()


async def mark_job_completed(db: AsyncSession, job: AccountingSyncJob) -> None:
    job.status = JOB_STATUS_COMPLETED
    job.finished_at = datetime.now(timezone.utc)
    job.error_code = None
    job.error_message = None
    await db.flush()


async def mark_job_failed(
    db: AsyncSession,
    job: AccountingSyncJob,
    *,
    error_code: str,
    error_message: str,
) -> None:
    job.status = JOB_STATUS_FAILED
    job.finished_at = datetime.now(timezone.utc)
    job.error_code = error_code[:64]
    job.error_message = error_message[:512]
    await db.flush()


async def cancel_pending_jobs(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    provider: str = AccountingProvider.XERO.value,
) -> int:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(AccountingSyncJob)
        .where(
            AccountingSyncJob.tenant_id == tenant_id,
            AccountingSyncJob.provider == provider,
            AccountingSyncJob.status.in_([JOB_STATUS_PENDING, JOB_STATUS_RUNNING]),
        )
        .values(
            status=JOB_STATUS_CANCELLED,
            finished_at=now,
            error_code="cancelled",
            error_message="Integration disconnected",
        )
    )
    return int(result.rowcount or 0)


async def get_latest_sync_job(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    provider: str = AccountingProvider.XERO.value,
) -> AccountingSyncJob | None:
    return (
        await db.execute(
            select(AccountingSyncJob)
            .where(
                AccountingSyncJob.tenant_id == tenant_id,
                AccountingSyncJob.provider == provider,
            )
            .order_by(AccountingSyncJob.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
