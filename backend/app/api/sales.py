"""Sales orders and three-way match API."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db
from app.schemas.common import ApiEnvelope
from app.schemas.sales import DeliveryNoteCreate, SalesOrderResponse, TwoWaySalesMatchResponse
from app.services.audit.audit_service import log_event
from app.services.auth.privilege_service import require_privilege
from app.services.sales.sales_match_service import (
    approve_sales_variance,
    filter_two_way_sales_rows,
    list_sales_orders,
    list_two_way_sales_orphans,
    record_delivery_note,
)

router = APIRouter(prefix="/sales", tags=["sales"])


@router.get("", response_model=ApiEnvelope[list[SalesOrderResponse]])
async def get_sales_orders(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[SalesOrderResponse]]:
    rows = await list_sales_orders(db, ctx.tenant_id)
    return ApiEnvelope(data=rows)


@router.get("/two-way", response_model=ApiEnvelope[dict])
async def get_two_way_sales_matches(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[dict]:
    all_rows = await list_sales_orders(db, ctx.tenant_id)
    register_rows = filter_two_way_sales_rows(all_rows)
    orphan_rows = await list_two_way_sales_orphans(db, ctx.tenant_id)
    return ApiEnvelope(
        data={
            "register_rows": register_rows,
            "orphan_rows": orphan_rows,
        }
    )


@router.post(
    "/{sales_order_id}/dn",
    response_model=ApiEnvelope[SalesOrderResponse],
)
async def post_delivery_note(
    sales_order_id: int,
    body: DeliveryNoteCreate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[SalesOrderResponse]:
    try:
        row = await record_delivery_note(db, ctx.tenant_id, sales_order_id, body)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc

    if row.invoice_id is not None:
        actor_name, actor_email = await actor_from_context(db, ctx)
        await log_event(
            db,
            "delivery_note_recorded",
            invoice_id=row.invoice_id,
            tenant_id=ctx.tenant_id,
            actor_name=actor_name,
            actor_email=actor_email,
            detail={
                "sales_order_id": sales_order_id,
                "so_number": row.so_number,
                "dn_qty": float(body.dn_qty),
                "shipper": body.shipper,
            },
        )

    return ApiEnvelope(data=row)


@router.post(
    "/{sales_order_id}/approve-variance",
    response_model=ApiEnvelope[SalesOrderResponse],
)
async def post_approve_sales_variance(
    sales_order_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[SalesOrderResponse]:
    require_privilege(ctx, "Approve")
    try:
        row = await approve_sales_variance(db, ctx.tenant_id, sales_order_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc

    if row.invoice_id is not None:
        actor_name, actor_email = await actor_from_context(db, ctx)
        await log_event(
            db,
            "sales_variance_approved",
            invoice_id=row.invoice_id,
            tenant_id=ctx.tenant_id,
            actor_name=actor_name,
            actor_email=actor_email,
            detail={
                "sales_order_id": sales_order_id,
                "so_number": row.so_number,
                "match_status": row.match.status,
            },
        )

    return ApiEnvelope(data=row)
