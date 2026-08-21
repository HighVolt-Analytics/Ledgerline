"""Purchase orders and three-way match API."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db
from app.schemas.common import ApiEnvelope
from app.schemas.purchase import GoodsReceiptCreate, PurchaseOrderResponse, PurchaseWorkspaceKpis
from app.services.audit.audit_service import log_event
from app.services.auth.privilege_service import require_privilege
from app.services.approval.approval_quorum_service import ApprovalQuorumForbiddenError
from app.services.purchase.purchase_match_service import (
    approve_purchase_variance,
    filter_two_way_purchase_rows,
    list_purchase_orders,
    purchase_workspace_kpis,
    record_goods_receipt,
)

router = APIRouter(prefix="/purchases", tags=["purchases"])


@router.get("", response_model=ApiEnvelope[list[PurchaseOrderResponse]])
async def get_purchase_orders(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[PurchaseOrderResponse]]:
    rows = await list_purchase_orders(db, ctx.tenant_id)
    return ApiEnvelope(data=rows)


@router.get("/two-way", response_model=ApiEnvelope[list[PurchaseOrderResponse]])
async def get_two_way_purchase_orders(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[PurchaseOrderResponse]]:
    rows = await list_purchase_orders(db, ctx.tenant_id)
    return ApiEnvelope(data=filter_two_way_purchase_rows(rows))


@router.get("/kpis", response_model=ApiEnvelope[PurchaseWorkspaceKpis])
async def get_purchase_workspace_kpis(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[PurchaseWorkspaceKpis]:
    awaiting, needs_action = await purchase_workspace_kpis(db, ctx.tenant_id)
    return ApiEnvelope(
        data=PurchaseWorkspaceKpis(
            awaiting_po_count=awaiting,
            needs_action_count=needs_action,
        )
    )


@router.post(
    "/{purchase_order_id}/grn",
    response_model=ApiEnvelope[PurchaseOrderResponse],
)
async def post_goods_receipt(
    purchase_order_id: int,
    body: GoodsReceiptCreate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[PurchaseOrderResponse]:
    try:
        row = await record_goods_receipt(db, ctx.tenant_id, purchase_order_id, body)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc

    if row.invoice_id is not None:
        actor_name, actor_email = await actor_from_context(db, ctx)
        await log_event(
            db,
            "goods_receipt_recorded",
            invoice_id=row.invoice_id,
            tenant_id=ctx.tenant_id,
            actor_name=actor_name,
            actor_email=actor_email,
            detail={
                "purchase_order_id": purchase_order_id,
                "po_number": row.po_number,
                "grn_qty": float(body.grn_qty),
                "receiver": body.receiver,
            },
        )

    return ApiEnvelope(data=row)


@router.post(
    "/{purchase_order_id}/approve-variance",
    response_model=ApiEnvelope[PurchaseOrderResponse],
)
async def post_approve_variance(
    purchase_order_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[PurchaseOrderResponse]:
    require_privilege(ctx, "Approve")
    try:
        row = await approve_purchase_variance(
            db, ctx.tenant_id, purchase_order_id, ctx=ctx
        )
    except ApprovalQuorumForbiddenError as exc:
        raise HTTPException(403, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc

    if row.invoice_id is not None and row.variance_approved:
        actor_name, actor_email = await actor_from_context(db, ctx)
        await log_event(
            db,
            "purchase_variance_approved",
            invoice_id=row.invoice_id,
            tenant_id=ctx.tenant_id,
            actor_name=actor_name,
            actor_email=actor_email,
            detail={
                "purchase_order_id": purchase_order_id,
                "po_number": row.po_number,
                "match_status": row.match.status,
            },
        )

    return ApiEnvelope(data=row)
