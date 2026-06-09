"""Document matrix — pipeline stages from server-side audit + status."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.api.invoices import _to_response
from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.common import ApiEnvelope, ResponseMeta
from app.schemas.pipeline import MatrixRowResponse
from app.services.pipeline_stages import build_matrix_cells

router = APIRouter(prefix="/matrix", tags=["matrix"])


async def _audit_logs_for_invoices(
    db: AsyncSession, invoice_ids: list[int]
) -> dict[int, list[AuditLog]]:
    if not invoice_ids:
        return {}
    rows = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.invoice_id.in_(invoice_ids))
            .order_by(AuditLog.created_at.desc())
        )
    ).scalars().all()
    grouped: dict[int, list[AuditLog]] = {i: [] for i in invoice_ids}
    for row in rows:
        if row.invoice_id is not None:
            grouped.setdefault(row.invoice_id, []).append(row)
    return grouped


@router.get("", response_model=ApiEnvelope[list[MatrixRowResponse]])
async def document_matrix(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    status: str | None = None,
    route_target: str | None = Query(None, description="Filter by rule book route target"),
    evaluation_status: str | None = Query(None, description="Filter by evaluation status"),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[MatrixRowResponse]]:
    """Invoices with server-computed pipeline stage cells."""
    stmt = (
        select(Invoice)
        .where(Invoice.org_id == ctx.org_id)
        .where(Invoice.status != InvoiceStatus.DUPLICATE_SKIPPED)
        .order_by(Invoice.created_at.desc())
    )
    count_stmt = select(func.count(Invoice.id)).where(
        Invoice.org_id == ctx.org_id,
        Invoice.status != InvoiceStatus.DUPLICATE_SKIPPED,
    )
    if status:
        try:
            status_enum = InvoiceStatus(status)
            stmt = stmt.where(Invoice.status == status_enum)
            count_stmt = count_stmt.where(Invoice.status == status_enum)
        except ValueError:
            pass
    if route_target and route_target.strip():
        stmt = stmt.where(Invoice.route_target == route_target.strip())
        count_stmt = count_stmt.where(Invoice.route_target == route_target.strip())
    if evaluation_status and evaluation_status.strip():
        stmt = stmt.where(Invoice.evaluation_status == evaluation_status.strip())
        count_stmt = count_stmt.where(Invoice.evaluation_status == evaluation_status.strip())

    total = (await db.execute(count_stmt)).scalar() or 0
    pages = max(1, (total + page_size - 1) // page_size)
    invoices = (
        await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()

    audit_by_id = await _audit_logs_for_invoices(db, [inv.id for inv in invoices])
    data = [
        MatrixRowResponse(
            invoice=_to_response(inv),
            stages=build_matrix_cells(inv, audit_by_id.get(inv.id, [])),
        )
        for inv in invoices
    ]
    return ApiEnvelope(data=data, meta=ResponseMeta(page=page, total=total, pages=pages))
