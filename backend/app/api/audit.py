from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.models.invoice import Invoice
from app.models.audit import AuditLog
from app.schemas.common import ApiEnvelope, ResponseMeta

router = APIRouter(prefix="/audit-log", tags=["audit"])


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    correlation_id: str | None
    event: str
    invoice_id: int | None
    detail: dict[str, object] | None
    created_at: datetime


@router.get("", response_model=ApiEnvelope[list[AuditLogResponse]])
async def list_audit_log(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    invoice_id: int | None = None,
    event: str | None = None,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[AuditLogResponse]]:
    org_filter = or_(
        AuditLog.org_id == ctx.org_id,
        AuditLog.invoice_id.in_(
            select(Invoice.id).where(Invoice.org_id == ctx.org_id)
        ),
    )
    stmt = select(AuditLog).where(org_filter).order_by(AuditLog.created_at.desc())
    count_stmt = select(func.count(AuditLog.id)).where(org_filter)
    if invoice_id is not None:
        stmt = stmt.where(AuditLog.invoice_id == invoice_id)
        count_stmt = count_stmt.where(AuditLog.invoice_id == invoice_id)
    if event:
        stmt = stmt.where(AuditLog.event == event)
        count_stmt = count_stmt.where(AuditLog.event == event)

    total = (await db.execute(count_stmt)).scalar() or 0
    pages = max(1, (total + page_size - 1) // page_size)
    rows = (
        await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()

    return ApiEnvelope(
        data=[AuditLogResponse.model_validate(r) for r in rows],
        meta=ResponseMeta(page=page, total=total, pages=pages),
    )
