"""Approval queue and kanban API orchestration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.approvals import ApprovalListRequest
from app.schemas.common import ResponseMeta
from app.schemas.invoice import InvoiceResponse
from app.services.approval.approval_board_service import approval_board_column
from app.services.approval.approval_service import (
    APPROVABLE_STATUSES,
    approve_invoice_for_reprocess,
    permanently_delete_invoice,
    reject_invoice,
    request_approval,
)
from app.services.shared.file_storage import ensure_stored_file_for_approval
from app.services.invoice.invoice_access_service import get_invoice_for_tenant
from app.services.invoice.invoice_response_service import (
    response_for_invoice,
    responses_for_approval_board,
    responses_for_invoices,
)

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


@dataclass(frozen=True)
class ApprovalListResult:
    rows: list[InvoiceResponse]
    meta: ResponseMeta | None = None


async def list_approvals_board(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> list[InvoiceResponse]:
    active_statuses = _QUEUE_STATUSES + _BOARD_PIPELINE_STATUSES
    active_rows = (
        await db.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.status.in_(active_statuses),
            )
            .order_by(Invoice.created_at.desc(), Invoice.id.desc())
        )
    ).scalars().all()
    processed_rows = (
        await db.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
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
    responses = await responses_for_approval_board(db, list(rows), tenant_id=tenant_id)
    by_id_inv = {inv.id: inv for inv in rows}
    enriched: list[InvoiceResponse] = []
    for resp in responses:
        inv = by_id_inv.get(resp.id)
        column = approval_board_column(inv) if inv is not None else None
        enriched.append(resp.model_copy(update={"approval_board_column": column}))
    return enriched


async def list_approvals_queue(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    params: ApprovalListRequest,
) -> ApprovalListResult:
    stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.status.in_(_QUEUE_STATUSES),
        )
        .order_by(Invoice.created_at.desc())
    )
    count_stmt = select(func.count(Invoice.id)).where(
        Invoice.tenant_id == tenant_id,
        Invoice.status.in_(_QUEUE_STATUSES),
    )

    total = (await db.execute(count_stmt)).scalar() or 0
    pages = max(1, (total + params.page_size - 1) // params.page_size)
    rows = (
        await db.execute(
            stmt.offset((params.page - 1) * params.page_size).limit(params.page_size)
        )
    ).scalars().all()

    return ApprovalListResult(
        rows=await responses_for_invoices(db, list(rows), tenant_id=tenant_id),
        meta=ResponseMeta(page=params.page, total=total, pages=pages),
    )


async def load_approvable_invoice(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
) -> Invoice:
    inv = await get_invoice_for_tenant(db, invoice_id, tenant_id)
    if inv.status == InvoiceStatus.PROCESSED:
        raise ValueError(
            "This invoice is already processed. Reject it first if you need "
            "to return it to the approval queue."
        )
    if inv.status not in APPROVABLE_STATUSES:
        raise ValueError(
            f"Invoice status '{inv.status.value}' is not in the approval queue"
        )
    return inv


async def approve_invoice_action(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    invoice_id: int,
) -> InvoiceResponse:
    inv = await load_approvable_invoice(
        db, tenant_id=ctx.tenant_id, invoice_id=invoice_id
    )
    await ensure_stored_file_for_approval(db, inv)
    actor_name, actor_email = await actor_from_context(db, ctx)
    await approve_invoice_for_reprocess(
        db, inv, actor_name=actor_name, actor_email=actor_email
    )
    return await response_for_invoice(db, inv, tenant_id=ctx.tenant_id)


async def reject_invoice_action(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    invoice_id: int,
) -> InvoiceResponse:
    inv = await get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    actor_name, actor_email = await actor_from_context(db, ctx)
    await reject_invoice(db, inv, actor_name=actor_name, actor_email=actor_email)
    return await response_for_invoice(db, inv, tenant_id=ctx.tenant_id)


async def request_approval_action(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    invoice_id: int,
) -> InvoiceResponse:
    inv = await get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    actor_name, actor_email = await actor_from_context(db, ctx)
    await request_approval(db, inv, actor_name=actor_name, actor_email=actor_email)
    return await response_for_invoice(db, inv, tenant_id=ctx.tenant_id)


async def permanently_delete_invoice_action(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    invoice_id: int,
) -> None:
    inv = await get_invoice_for_tenant(db, invoice_id, ctx.tenant_id)
    await permanently_delete_invoice(db, inv)
