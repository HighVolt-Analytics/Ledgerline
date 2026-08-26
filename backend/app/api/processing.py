from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.api.http_errors import http_bad_request, http_not_found
from app.schemas.common import ApiEnvelope
from app.schemas.processing_api import TriggerProcessingRequest
from app.services.invoice.processing_api_service import (
    queue_processing,
    validate_mailbox_for_processing,
)
from app.workers.tasks import get_processing_status

router = APIRouter(prefix="/process", tags=["processing"])


class ProcessingStatus(BaseModel):
    state: str
    last_run: str | None = None
    active_tasks: int = 0


@router.post("/trigger", response_model=ApiEnvelope[dict[str, str]])
async def trigger_processing(
    background_tasks: BackgroundTasks,
    body: TriggerProcessingRequest | None = None,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[dict[str, str]]:
    mailbox_id = body.mailbox_id if body else None
    if mailbox_id is not None:
        try:
            await validate_mailbox_for_processing(
                db, tenant_id=ctx.tenant_id, mailbox_id=mailbox_id
            )
        except LookupError as exc:
            raise http_not_found(exc) from exc
        except ValueError as exc:
            raise http_bad_request(exc) from exc

    result = await queue_processing(
        mailbox_id=mailbox_id,
        tenant_id=ctx.tenant_id,
        background_tasks=background_tasks,
    )
    return ApiEnvelope(data={"task_id": result.task_id, "status": result.status})


@router.get("/status", response_model=ApiEnvelope[ProcessingStatus])
async def processing_status() -> ApiEnvelope[ProcessingStatus]:
    return ApiEnvelope(data=ProcessingStatus(**(await get_processing_status())))
