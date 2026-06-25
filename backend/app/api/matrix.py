"""Document matrix — pipeline stages from server-side audit + status."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.api.invoices import _to_response
from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment
from app.schemas.common import ApiEnvelope, ResponseMeta
from app.schemas.pipeline import MatrixRowResponse
from app.services.matrix_service import (
    derive_matrix_flag,
    derive_matrix_payment_status,
    duplicate_conflict_for_invoice,
)
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


async def _payments_for_invoices(
    db: AsyncSession,
    tenant_id: int,
    invoice_ids: list[int],
) -> dict[int, Payment]:
    if not invoice_ids:
        return {}
    rows = (
        await db.execute(
            select(Payment).where(
                Payment.tenant_id == tenant_id,
                Payment.invoice_id.in_(invoice_ids),
            )
        )
    ).scalars().all()
    return {row.invoice_id: row for row in rows}


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
    """Invoices with server-computed pipeline stage cells, flags, and payment readiness."""
    stmt = (
        select(Invoice)
        .where(Invoice.tenant_id == ctx.tenant_id)
        .order_by(Invoice.created_at.desc(), Invoice.id.desc())
    )
    count_stmt = select(func.count(Invoice.id)).where(Invoice.tenant_id == ctx.tenant_id)
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

    invoice_ids = [inv.id for inv in invoices]
    audit_by_id = await _audit_logs_for_invoices(db, invoice_ids)
    payments_by_id = await _payments_for_invoices(db, ctx.tenant_id, invoice_ids)
    from app.services.publish_service import published_invoice_ids

    published_ids = await published_invoice_ids(db, invoice_ids)

    data: list[MatrixRowResponse] = []
    for inv in invoices:
        flag, flag_reason = derive_matrix_flag(inv)
        payment = payments_by_id.get(inv.id)
        conflict_with, conflict_detail = await duplicate_conflict_for_invoice(db, ctx.tenant_id, inv)
        data.append(
            MatrixRowResponse(
                invoice=_to_response(
                    inv,
                    published_to_ledger=inv.id in published_ids,
                    audit_logs=audit_by_id.get(inv.id, []),
                ),
                stages=build_matrix_cells(inv, audit_by_id.get(inv.id, [])),
                flag=flag,
                flag_reason=flag_reason,
                payment_status=derive_matrix_payment_status(inv, payment),
                conflict_with=conflict_with,
                conflict_detail=conflict_detail or None,
            )
        )
    return ApiEnvelope(data=data, meta=ResponseMeta(page=page, total=total, pages=pages))
