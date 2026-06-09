"""Vendor master CRUD — rule book detection source of truth."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db, require_admin
from app.schemas.common import ApiEnvelope
from app.schemas.master_data import (
    VendorMasterCreate,
    VendorMasterResponse,
    VendorMasterUpdate,
)
from app.services.master_data_service import (
    create_vendor_master,
    delete_vendor_master,
    list_vendor_masters,
    update_vendor_master,
)

router = APIRouter(prefix="/vendor-masters", tags=["vendor-masters"])


@router.get("", response_model=ApiEnvelope[list[VendorMasterResponse]])
async def list_vendor_master_records(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[VendorMasterResponse]]:
    rows = await list_vendor_masters(db, ctx.org_id)
    return ApiEnvelope(data=rows)


@router.post("", response_model=ApiEnvelope[VendorMasterResponse], status_code=201)
async def create_vendor_master_record(
    body: VendorMasterCreate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[VendorMasterResponse]:
    try:
        row = await create_vendor_master(db, ctx.org_id, body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return ApiEnvelope(data=row)


@router.patch("/{master_id}", response_model=ApiEnvelope[VendorMasterResponse])
async def update_vendor_master_record(
    master_id: str,
    body: VendorMasterUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[VendorMasterResponse]:
    try:
        row = await update_vendor_master(db, ctx.org_id, master_id, body)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return ApiEnvelope(data=row)


@router.delete("/{master_id}", status_code=204)
async def delete_vendor_master_record(
    master_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> None:
    try:
        await delete_vendor_master(db, ctx.org_id, master_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
