"""Approval queue — invoices needing human review (exceptions)."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.api.http_errors import http_bad_request, http_not_found
from app.schemas.approvals import ApprovalListRequest
from app.schemas.common import ApiEnvelope
from app.schemas.invoice import InvoiceResponse
from app.services.approval.approval_api_service import (
    approve_invoice_action,
    list_approvals_board,
    list_approvals_queue,
    permanently_delete_invoice_action,
    reject_invoice_action,
    request_approval_action,
)
from app.services.auth.privilege_service import require_privilege
from app.workers.tasks import process_invoice_background

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("/board", response_model=ApiEnvelope[list[InvoiceResponse]])
async def list_approvals_board_route(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[InvoiceResponse]]:
    """
    All invoices shown on the approvals kanban (one round-trip).

    Includes queue, pipeline, and the most recent processed rows.
    """
    return ApiEnvelope(data=await list_approvals_board(db, tenant_id=ctx.tenant_id))


@router.get("", response_model=ApiEnvelope[list[InvoiceResponse]])
async def list_approvals(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[InvoiceResponse]]:
    """Invoices in the approval queue (exceptions, duplicates, rejected)."""
    params = ApprovalListRequest(page=page, page_size=page_size)
    result = await list_approvals_queue(db, tenant_id=ctx.tenant_id, params=params)
    return ApiEnvelope(data=result.rows, meta=result.meta)


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
    try:
        response = await approve_invoice_action(db, ctx, invoice_id=invoice_id)
    except LookupError as exc:
        raise http_not_found(exc) from exc
    except ValueError as exc:
        raise http_bad_request(exc) from exc
    await db.commit()
    background_tasks.add_task(
        process_invoice_background, invoice_id, tenant_id=ctx.tenant_id
    )
    return ApiEnvelope(data=response)


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
    try:
        response = await reject_invoice_action(db, ctx, invoice_id=invoice_id)
    except LookupError as exc:
        raise http_not_found(exc) from exc
    except ValueError as exc:
        raise http_bad_request(exc) from exc
    return ApiEnvelope(data=response)


@router.post("/{invoice_id}/request", response_model=ApiEnvelope[InvoiceResponse])
async def request_approval_route(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[InvoiceResponse]:
    """Route an invoice to the approval queue for human review."""
    try:
        response = await request_approval_action(db, ctx, invoice_id=invoice_id)
    except LookupError as exc:
        raise http_not_found(exc) from exc
    except ValueError as exc:
        raise http_bad_request(exc) from exc
    return ApiEnvelope(data=response)


@router.delete("/{invoice_id}", status_code=204)
async def permanently_delete_invoice_route(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> None:
    """Permanently delete a rejected or duplicate-skipped invoice and its stored file."""
    require_privilege(ctx, "Reject")
    try:
        await permanently_delete_invoice_action(db, ctx, invoice_id=invoice_id)
    except LookupError as exc:
        raise http_not_found(exc) from exc
    except ValueError as exc:
        raise http_bad_request(exc) from exc
