"""Approval queue — invoices needing human review (exceptions)."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db
from app.api.invoices import _response_for_invoice, _responses_for_invoices
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.common import ApiEnvelope, ResponseMeta
from app.schemas.invoice import InvoiceResponse
from app.services.approval_service import (
    APPROVABLE_STATUSES,
    approve_invoice_for_reprocess,
    permanently_delete_invoice,
    reject_invoice,
    request_approval,
)
from app.services.file_storage import ensure_stored_file_for_approval, repair_invoice_stored_path
from app.services.privilege_service import require_privilege
from app.workers.tasks import process_invoice_background

router = APIRouter(prefix="/approvals", tags=["approvals"])

_QUEUE_STATUSES = (
    InvoiceStatus.EXCEPTION,
    InvoiceStatus.DUPLICATE_SKIPPED,
    InvoiceStatus.REJECTED,
)

_BOARD_PIPELINE_STATUSES = (
    InvoiceStatus.PENDING,
    InvoiceStatus.PARSING,
    InvoiceStatus.VALIDATING,
    InvoiceStatus.MAPPING,
    InvoiceStatus.JOURNALING,
    InvoiceStatus.RECONCILING,
)

_BOARD_PROCESSED_LIMIT = 100


@router.get("/board", response_model=ApiEnvelope[list[InvoiceResponse]])
async def list_approvals_board(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[InvoiceResponse]]:
    """
    All invoices shown on the approvals kanban (one round-trip).

    Includes queue, pipeline, and the most recent processed rows.
    """
    active_statuses = _QUEUE_STATUSES + _BOARD_PIPELINE_STATUSES
    active_rows = (
        await db.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == ctx.tenant_id,
                Invoice.status.in_(active_statuses),
            )
            .order_by(Invoice.created_at.desc(), Invoice.id.desc())
        )
    ).scalars().all()
    processed_rows = (
        await db.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == ctx.tenant_id,
                Invoice.status == InvoiceStatus.PROCESSED,
            )
            .order_by(Invoice.created_at.desc(), Invoice.id.desc())
            .limit(_BOARD_PROCESSED_LIMIT)
        )
    ).scalars().all()
    by_id: dict[int, Invoice] = {}
    for row in (*active_rows, *processed_rows):
        by_id[row.id] = row
    rows = sorted(
        by_id.values(),
        key=lambda inv: (inv.created_at, inv.id),
        reverse=True,
    )
    responses = await _responses_for_invoices(db, list(rows))
    from app.services.approval_board_service import approval_board_column

    enriched: list[InvoiceResponse] = []
    by_id_inv = {inv.id: inv for inv in rows}
    for resp in responses:
        inv = by_id_inv.get(resp.id)
        column = approval_board_column(inv) if inv is not None else None
        enriched.append(resp.model_copy(update={"approval_board_column": column}))
    return ApiEnvelope(data=enriched)


@router.get("", response_model=ApiEnvelope[list[InvoiceResponse]])
async def list_approvals(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[InvoiceResponse]]:
    """Invoices in the approval queue (exceptions, duplicates, rejected)."""
    stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == ctx.tenant_id,
            Invoice.status.in_(_QUEUE_STATUSES),
        )
        .order_by(Invoice.created_at.desc())
    )
    count_stmt = select(func.count(Invoice.id)).where(
        Invoice.tenant_id == ctx.tenant_id,
        Invoice.status.in_(_QUEUE_STATUSES),
    )

    total = (await db.execute(count_stmt)).scalar() or 0
    pages = max(1, (total + page_size - 1) // page_size)
    rows = (
        await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()

    return ApiEnvelope(
        data=await _responses_for_invoices(db, list(rows)),
        meta=ResponseMeta(page=page, total=total, pages=pages),
    )


@router.post("/{invoice_id}/approve", response_model=ApiEnvelope[InvoiceResponse])
async def approve_invoice(
    invoice_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[InvoiceResponse]:
    """
    Approve an exception/rejected invoice for reprocessing.

    Restores rejected blobs to invoice/ layout when needed, resets to pending,
    then queues the invoice pipeline for this row.
    """
    require_privilege(ctx, "Approve")
    inv = await db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Invoice not found")
    if inv.status == InvoiceStatus.PROCESSED:
        raise HTTPException(
            400,
            "This invoice is already processed. Reject it first if you need to return it to the approval queue.",
        )
    if inv.status not in APPROVABLE_STATUSES:
        raise HTTPException(
            400,
            f"Invoice status '{inv.status.value}' is not in the approval queue",
        )
    try:
        await ensure_stored_file_for_approval(db, inv)
        actor_name, actor_email = await actor_from_context(db, ctx)
        await approve_invoice_for_reprocess(
            db, inv, actor_name=actor_name, actor_email=actor_email
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    # Commit before background task so process_invoice sees pending (not exception/rejected).
    await db.commit()
    background_tasks.add_task(process_invoice_background, invoice_id, tenant_id=ctx.tenant_id)
    return ApiEnvelope(data=await _response_for_invoice(db, inv))


@router.post("/{invoice_id}/reject", response_model=ApiEnvelope[InvoiceResponse])
async def reject_invoice_route(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[InvoiceResponse]:
    """
    Reject an exception invoice.

    Sets status to rejected and moves the stored file to
    rejected/{org}/{vendor}/{year}/{month}/ in blob storage.
    """
    require_privilege(ctx, "Reject")
    inv = await db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Invoice not found")
    try:
        actor_name, actor_email = await actor_from_context(db, ctx)
        await reject_invoice(db, inv, actor_name=actor_name, actor_email=actor_email)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ApiEnvelope(data=await _response_for_invoice(db, inv))


@router.post("/{invoice_id}/request", response_model=ApiEnvelope[InvoiceResponse])
async def request_approval_route(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[InvoiceResponse]:
    """Route an invoice to the approval queue for human review."""
    inv = await db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Invoice not found")
    try:
        actor_name, actor_email = await actor_from_context(db, ctx)
        await request_approval(db, inv, actor_name=actor_name, actor_email=actor_email)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ApiEnvelope(data=await _response_for_invoice(db, inv))


@router.delete("/{invoice_id}", status_code=204)
async def permanently_delete_invoice_route(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> None:
    """Permanently delete a rejected or duplicate-skipped invoice and its stored file."""
    require_privilege(ctx, "Reject")
    inv = await db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Invoice not found")
    try:
        await permanently_delete_invoice(db, inv)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
