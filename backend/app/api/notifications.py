from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.schemas.common import ApiEnvelope
from app.schemas.notifications import MarkNotificationsReadResponse, NotificationsResponse
from app.services.notifications.notification_service import (
    fetch_notifications,
    mark_notifications_read,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=ApiEnvelope[NotificationsResponse])
async def list_notifications(
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[NotificationsResponse]:
    return ApiEnvelope(
        data=await fetch_notifications(
            db,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            limit=limit,
        )
    )


@router.post("/mark-read", response_model=ApiEnvelope[MarkNotificationsReadResponse])
async def mark_read(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[MarkNotificationsReadResponse]:
    return ApiEnvelope(
        data=await mark_notifications_read(
            db,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
        )
    )
