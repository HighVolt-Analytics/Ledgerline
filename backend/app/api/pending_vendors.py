"""Pending vendor registration queue."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.schemas.common import ApiEnvelope
from app.schemas.master_data import (
    PendingVendorCreate,
    PendingVendorPromote,
    PendingVendorResponse,
    VendorMasterResponse,
)
from app.services.master_data_service import (
    create_pending_vendor,
    dismiss_pending_vendor,
    list_pending_vendors,
    promote_pending_vendor,
)

router = APIRouter(prefix="/pending-vendors", tags=["pending-vendors"])


@router.get("", response_model=ApiEnvelope[list[PendingVendorResponse]])
async def list_pending_vendor_records(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[PendingVendorResponse]]:
    rows = await list_pending_vendors(db, ctx.tenant_id)
    return ApiEnvelope(data=rows)


@router.post("", response_model=ApiEnvelope[PendingVendorResponse], status_code=201)
async def create_pending_vendor_record(
    body: PendingVendorCreate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[PendingVendorResponse]:
    row = await create_pending_vendor(db, ctx.tenant_id, body)
    return ApiEnvelope(data=row)


@router.post("/{pending_id}/promote", response_model=ApiEnvelope[VendorMasterResponse])
async def promote_pending_vendor_record(
    pending_id: int,
    body: PendingVendorPromote,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[VendorMasterResponse]:
    try:
        vendor = await promote_pending_vendor(db, ctx.tenant_id, pending_id, body)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return ApiEnvelope(data=vendor)


@router.post("/{pending_id}/dismiss", status_code=204)
async def dismiss_pending_vendor_record(
    pending_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> None:
    try:
        await dismiss_pending_vendor(db, ctx.tenant_id, pending_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
