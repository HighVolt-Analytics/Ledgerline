"""Vendor registry CRUD."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db
from app.api.http_errors import http_not_found, http_payout_method_error
from app.schemas.common import ApiEnvelope
from app.schemas.vendor import (
    VendorActivityRow,
    VendorCreate,
    VendorPayoutMethodCreate,
    VendorPayoutMethodResponse,
    VendorPayoutMethodUpdate,
    VendorResponse,
    VendorUpdate,
)
from app.services.audit.audit_service import log_event
from app.services.master_data.vendor_payout_method_service import (
    VendorPayoutMethodError,
    create_payout_method_for_vendor,
    delete_payout_method_for_vendor,
    list_payout_methods_for_vendor,
    update_payout_method_for_vendor,
)
from app.services.master_data.vendor_registry_service import (
    create_vendor_registry,
    delete_vendor_registry,
    list_vendor_activity,
    list_vendor_registry,
    update_vendor_registry,
)

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.get("", response_model=ApiEnvelope[list[VendorResponse]])
async def list_vendors(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[VendorResponse]]:
    return ApiEnvelope(data=await list_vendor_registry(db, tenant_id=ctx.tenant_id))


@router.get("/activity", response_model=ApiEnvelope[list[VendorActivityRow]])
async def list_vendor_activity_route(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[VendorActivityRow]]:
    return ApiEnvelope(data=await list_vendor_activity(db, tenant_id=ctx.tenant_id))


@router.post("", response_model=ApiEnvelope[VendorResponse], status_code=201)
async def create_vendor(
    body: VendorCreate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[VendorResponse]:
    try:
        row = await create_vendor_registry(db, tenant_id=ctx.tenant_id, body=body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return ApiEnvelope(data=row)


@router.patch("/{vendor_id}", response_model=ApiEnvelope[VendorResponse])
async def update_vendor(
    vendor_id: int,
    body: VendorUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[VendorResponse]:
    try:
        row = await update_vendor_registry(
            db, tenant_id=ctx.tenant_id, vendor_id=vendor_id, body=body
        )
    except LookupError as exc:
        raise http_not_found(exc) from exc
    return ApiEnvelope(data=row)


@router.delete("/{vendor_id}", status_code=204)
async def delete_vendor(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> None:
    try:
        await delete_vendor_registry(db, tenant_id=ctx.tenant_id, vendor_id=vendor_id)
    except LookupError as exc:
        raise http_not_found(exc) from exc


@router.get(
    "/{vendor_id}/payout-methods",
    response_model=ApiEnvelope[list[VendorPayoutMethodResponse]],
)
async def list_vendor_payout_methods(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[VendorPayoutMethodResponse]]:
    try:
        rows = await list_payout_methods_for_vendor(db, ctx.tenant_id, vendor_id)
    except LookupError as exc:
        raise http_not_found(exc) from exc
    return ApiEnvelope(data=rows)


@router.post(
    "/{vendor_id}/payout-methods",
    response_model=ApiEnvelope[VendorPayoutMethodResponse],
    status_code=201,
)
async def create_vendor_payout_method(
    vendor_id: int,
    body: VendorPayoutMethodCreate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[VendorPayoutMethodResponse]:
    try:
        row = await create_payout_method_for_vendor(db, ctx.tenant_id, vendor_id, body)
    except LookupError as exc:
        raise http_not_found(exc) from exc
    except VendorPayoutMethodError as exc:
        raise http_payout_method_error(exc) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    await log_event(
        db,
        "vendor_payout_method_created",
        tenant_id=ctx.tenant_id,
        detail={
            "vendor_id": vendor_id,
            "method_id": row.id,
            "method_type": row.method_type,
            "status": row.status,
        },
        actor_name=actor_name,
        actor_email=actor_email,
    )
    return ApiEnvelope(data=row)


@router.patch(
    "/{vendor_id}/payout-methods/{method_id}",
    response_model=ApiEnvelope[VendorPayoutMethodResponse],
)
async def patch_vendor_payout_method(
    vendor_id: int,
    method_id: int,
    body: VendorPayoutMethodUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[VendorPayoutMethodResponse]:
    try:
        row = await update_payout_method_for_vendor(
            db, ctx.tenant_id, vendor_id, method_id, body
        )
    except LookupError as exc:
        raise http_not_found(exc) from exc
    except VendorPayoutMethodError as exc:
        raise http_payout_method_error(exc) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    await log_event(
        db,
        "vendor_payout_method_updated",
        tenant_id=ctx.tenant_id,
        detail={
            "vendor_id": vendor_id,
            "method_id": row.id,
            "method_type": row.method_type,
            "status": row.status,
        },
        actor_name=actor_name,
        actor_email=actor_email,
    )
    return ApiEnvelope(data=row)


@router.delete("/{vendor_id}/payout-methods/{method_id}", status_code=204)
async def delete_vendor_payout_method(
    vendor_id: int,
    method_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> None:
    try:
        await delete_payout_method_for_vendor(db, ctx.tenant_id, vendor_id, method_id)
    except LookupError as exc:
        raise http_not_found(exc) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    await log_event(
        db,
        "vendor_payout_method_deleted",
        tenant_id=ctx.tenant_id,
        detail={"vendor_id": vendor_id, "method_id": method_id},
        actor_name=actor_name,
        actor_email=actor_email,
    )
