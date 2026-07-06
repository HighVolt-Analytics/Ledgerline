"""Pending customer registration queue."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.schemas.common import ApiEnvelope
from app.schemas.customer import CustomerMasterResponse
from app.schemas.master_data import (
    PendingCustomerCreate,
    PendingCustomerPromote,
    PendingCustomerResponse,
)
from app.services.master_data.customer_master_service import (
    create_pending_customer,
    dismiss_pending_customer,
    list_pending_customers,
    promote_pending_customer,
)

router = APIRouter(prefix="/pending-customers", tags=["pending-customers"])


@router.get("", response_model=ApiEnvelope[list[PendingCustomerResponse]])
async def list_pending_customer_records(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[PendingCustomerResponse]]:
    rows = await list_pending_customers(db, ctx.tenant_id)
    return ApiEnvelope(data=rows)


@router.post("", response_model=ApiEnvelope[PendingCustomerResponse], status_code=201)
async def create_pending_customer_record(
    body: PendingCustomerCreate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[PendingCustomerResponse]:
    row = await create_pending_customer(db, ctx.tenant_id, body)
    return ApiEnvelope(data=row)


@router.post("/{pending_id}/promote", response_model=ApiEnvelope[CustomerMasterResponse])
async def promote_pending_customer_record(
    pending_id: int,
    body: PendingCustomerPromote,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[CustomerMasterResponse]:
    try:
        customer = await promote_pending_customer(db, ctx.tenant_id, pending_id, body)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return ApiEnvelope(data=customer)


@router.post("/{pending_id}/dismiss", status_code=204)
async def dismiss_pending_customer_record(
    pending_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> None:
    try:
        await dismiss_pending_customer(db, ctx.tenant_id, pending_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
