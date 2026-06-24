from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.models.invoice import Invoice
from app.models.audit import AuditLog
from app.schemas.common import ApiEnvelope, ResponseMeta
from app.services.audit_export_service import (
    audit_rows_to_csv,
    fetch_audit_rows_for_export,
    resolve_audit_export_range,
)

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
    if invoice_id is not None:
        inv = await db.get(Invoice, invoice_id)
        if not inv or inv.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "Invoice not found")

    org_filter = or_(
        AuditLog.tenant_id == ctx.tenant_id,
        AuditLog.invoice_id.in_(
            select(Invoice.id).where(Invoice.tenant_id == ctx.tenant_id)
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


def _audit_export_filename(
    *,
    month: str | None,
    date_from: date | None,
    date_to: date | None,
) -> str:
    if month:
        return f"audit_log_{month}.csv"
    if date_from and date_to and date_from == date_to:
        return f"audit_log_{date_from.isoformat()}.csv"
    if date_from and date_to:
        return f"audit_log_{date_from.isoformat()}_to_{date_to.isoformat()}.csv"
    if date_from:
        return f"audit_log_from_{date_from.isoformat()}.csv"
    if date_to:
        return f"audit_log_to_{date_to.isoformat()}.csv"
    return "audit_log.csv"


@router.get("/export")
async def export_audit_log_csv(
    month: str | None = Query(
        None,
        description="Period as YYYY-MM (same as Reports analytics)",
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
    ),
    date_from: date | None = Query(None, description="Inclusive start (created_at)"),
    date_to: date | None = Query(None, description="Inclusive end (created_at)"),
    document_only: bool = Query(
        True,
        description="Exclude config noise (rule_book_updated, invoices_remapped) and rows without invoice_id",
    ),
    dedupe: bool = Query(
        True,
        description="Keep only the latest row per invoice+event for high-churn lifecycle echoes",
    ),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> Response:
    """Download audit trail as CSV for the organisation."""
    try:
        d_from, d_to = resolve_audit_export_range(
            month=month,
            date_from=date_from,
            date_to=date_to,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    rows, invoice_map, purchase_by_po_id, purchase_by_po_number, linked_docs = (
        await fetch_audit_rows_for_export(
            db,
            tenant_id=ctx.tenant_id,
            date_from=d_from,
            date_to=d_to,
            document_only=document_only,
            dedupe=dedupe,
        )
    )
    csv_text = audit_rows_to_csv(
        rows,
        invoice_map=invoice_map,
        purchase_vault_by_po_id=purchase_by_po_id,
        purchase_vault_by_po_number=purchase_by_po_number,
        linked_docs_by_invoice=linked_docs,
    )
    filename = _audit_export_filename(month=month, date_from=d_from, date_to=d_to)
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
