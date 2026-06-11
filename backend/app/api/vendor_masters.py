"""Vendor master CRUD — rule book detection source of truth."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db, require_admin
from app.services.audit_service import log_event
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
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[VendorMasterResponse]:
    try:
        row = await create_vendor_master(db, ctx.org_id, body)
    except ValueError as exc:
        message = str(exc)
        status = 409 if "already exists" in message.lower() else 400
        raise HTTPException(status, message) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "vendor_master_created",
        org_id=ctx.org_id,
        detail={"master_id": row.id, "name": row.name, "after": row.model_dump()},
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
    return ApiEnvelope(data=row)


@router.patch("/{master_id}", response_model=ApiEnvelope[VendorMasterResponse])
async def update_vendor_master_record(
    master_id: str,
    body: VendorMasterUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[VendorMasterResponse]:
    before_rows = await list_vendor_masters(db, ctx.org_id)
    before = next((row for row in before_rows if row.id == master_id), None)
    try:
        row = await update_vendor_master(db, ctx.org_id, master_id, body)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    client_ip = request.client.host if request.client else None
    await log_event(
        db,
        "vendor_master_updated",
        org_id=ctx.org_id,
        detail={
            "master_id": master_id,
            "before": before.model_dump() if before else None,
            "after": row.model_dump(),
        },
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
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
