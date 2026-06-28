"""Vendor registry CRUD."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_auth_context, get_db
from app.models.vendor import VendorRegistry
from app.schemas.common import ApiEnvelope
from app.schemas.vendor import (
    VendorCreate,
    VendorPayoutMethodCreate,
    VendorPayoutMethodResponse,
    VendorPayoutMethodUpdate,
    VendorResponse,
    VendorUpdate,
)
from app.services.vendor_payout_method_service import (
    VendorPayoutMethodError,
    create_payout_method_for_vendor,
    delete_payout_method_for_vendor,
    list_payout_methods_for_vendor,
    update_payout_method_for_vendor,
)
from app.services.audit_service import log_event

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.get("", response_model=ApiEnvelope[list[VendorResponse]])
async def list_vendors(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[VendorResponse]]:
    rows = (
        await db.execute(
            select(VendorRegistry)
            .where(VendorRegistry.tenant_id == ctx.tenant_id)
            .order_by(VendorRegistry.vendor_name)
        )
    ).scalars().all()
    return ApiEnvelope(data=[VendorResponse.model_validate(r) for r in rows])


@router.post("", response_model=ApiEnvelope[VendorResponse], status_code=201)
async def create_vendor(
    body: VendorCreate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[VendorResponse]:
    existing = (
        await db.execute(
            select(VendorRegistry).where(
                VendorRegistry.tenant_id == ctx.tenant_id,
                VendorRegistry.vendor_slug == body.vendor_slug,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"Vendor slug '{body.vendor_slug}' already exists")

    row = VendorRegistry(
        tenant_id=ctx.tenant_id,
        vendor_slug=body.vendor_slug,
        vendor_name=body.vendor_name,
        sender_pattern=body.sender_pattern,
        abn=body.abn,
        approved=body.approved,
    )
    db.add(row)
    await db.flush()
    return ApiEnvelope(data=VendorResponse.model_validate(row))


@router.patch("/{vendor_id}", response_model=ApiEnvelope[VendorResponse])
async def update_vendor(
    vendor_id: int,
    body: VendorUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[VendorResponse]:
    row = await db.get(VendorRegistry, vendor_id)
    if not row or row.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Vendor not found")

    if body.vendor_name is not None:
        row.vendor_name = body.vendor_name
    if body.sender_pattern is not None:
        row.sender_pattern = body.sender_pattern
    if body.abn is not None:
        row.abn = body.abn
    if body.approved is not None:
        row.approved = body.approved

    await db.flush()
    return ApiEnvelope(data=VendorResponse.model_validate(row))


@router.delete("/{vendor_id}", status_code=204)
async def delete_vendor(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> None:
    row = await db.get(VendorRegistry, vendor_id)
    if not row or row.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Vendor not found")
    await db.delete(row)
    await db.flush()


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
        raise HTTPException(404, str(exc)) from exc
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
        raise HTTPException(404, str(exc)) from exc
    except VendorPayoutMethodError as exc:
        raise HTTPException(400, str(exc)) from exc
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
        raise HTTPException(404, str(exc)) from exc
    except VendorPayoutMethodError as exc:
        raise HTTPException(400, str(exc)) from exc
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
        raise HTTPException(404, str(exc)) from exc
    actor_name, actor_email = await actor_from_context(db, ctx)
    await log_event(
        db,
        "vendor_payout_method_deleted",
        tenant_id=ctx.tenant_id,
        detail={"vendor_id": vendor_id, "method_id": method_id},
        actor_name=actor_name,
        actor_email=actor_email,
    )
