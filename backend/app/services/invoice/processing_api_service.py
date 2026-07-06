"""Manual processing trigger orchestration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.connected_mailbox import ConnectedMailbox
from app.tenant_scoped import get_for_tenant


@dataclass(frozen=True)
class ProcessingTriggerResult:
    task_id: str
    status: str


async def validate_mailbox_for_processing(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    mailbox_id: int,
) -> None:
    mb = await get_for_tenant(db, ConnectedMailbox, mailbox_id, tenant_id)
    if not mb:
        raise LookupError("Mailbox not found")
    if not mb.is_active:
        raise ValueError("Mailbox is paused")
    if not mb.is_pollable:
        detail = mb.last_error or "Mailbox is not connected — send a reconnect invitation"
        raise ValueError(detail)


async def queue_processing(
    *,
    mailbox_id: int | None,
    tenant_id: uuid.UUID,
    background_tasks,
) -> ProcessingTriggerResult:
    settings = get_settings()
    poll_inbox = True
    if settings.sync_processing:
        from app.workers.tasks import run_pipeline_background

        background_tasks.add_task(
            run_pipeline_background,
            mailbox_id=mailbox_id,
            tenant_id=tenant_id,
            poll_inbox=poll_inbox,
        )
        return ProcessingTriggerResult(task_id="inline", status="running")

    try:
        from app.workers.tasks import process_inbox_task

        task = process_inbox_task.delay(mailbox_id=mailbox_id, tenant_id=tenant_id)
        return ProcessingTriggerResult(task_id=task.id, status="queued")
    except Exception:
        from app.workers.tasks import run_pipeline_background

        background_tasks.add_task(
            run_pipeline_background,
            mailbox_id=mailbox_id,
            tenant_id=tenant_id,
            poll_inbox=poll_inbox,
        )
        return ProcessingTriggerResult(task_id="inline", status="running")
