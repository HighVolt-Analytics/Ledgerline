from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.config import get_settings
from app.models.connected_mailbox import ConnectedMailbox
from app.schemas.common import ApiEnvelope
from app.workers.tasks import get_processing_status, run_pipeline_background

router = APIRouter(prefix="/process", tags=["processing"])


class ProcessingStatus(BaseModel):
    state: str
    last_run: str | None = None
    active_tasks: int = 0


class TriggerProcessingBody(BaseModel):
    mailbox_id: int | None = None


@router.post("/trigger", response_model=ApiEnvelope[dict[str, str]])
async def trigger_processing(
    background_tasks: BackgroundTasks,
    body: TriggerProcessingBody | None = None,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[dict[str, str]]:
    mailbox_id = body.mailbox_id if body else None
    org_id = ctx.org_id
    if mailbox_id is not None:
        mb = await db.get(ConnectedMailbox, mailbox_id)
        if not mb or mb.org_id != ctx.org_id:
            raise HTTPException(404, "Mailbox not found")
        if not mb.is_active:
            raise HTTPException(400, "Mailbox is paused")

    settings = get_settings()
    poll_inbox = True
    if settings.sync_processing:
        background_tasks.add_task(
            run_pipeline_background,
            mailbox_id=mailbox_id,
            org_id=org_id,
            poll_inbox=poll_inbox,
        )
        return ApiEnvelope(data={"task_id": "inline", "status": "running"})

    try:
        from app.workers.tasks import process_inbox_task

        task = process_inbox_task.delay(mailbox_id=mailbox_id, org_id=org_id)
        return ApiEnvelope(data={"task_id": task.id, "status": "queued"})
    except Exception:
        background_tasks.add_task(
            run_pipeline_background,
            mailbox_id=mailbox_id,
            org_id=org_id,
            poll_inbox=poll_inbox,
        )
        return ApiEnvelope(data={"task_id": "inline", "status": "running"})


@router.get("/status", response_model=ApiEnvelope[ProcessingStatus])
async def processing_status() -> ApiEnvelope[ProcessingStatus]:
    return ApiEnvelope(data=ProcessingStatus(**get_processing_status()))
