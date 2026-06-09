"""Vendor registry CRUD."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.models.vendor import VendorRegistry
from app.schemas.common import ApiEnvelope
from app.schemas.vendor import VendorCreate, VendorResponse, VendorUpdate

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.get("", response_model=ApiEnvelope[list[VendorResponse]])
async def list_vendors(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[VendorResponse]]:
    rows = (
        await db.execute(
            select(VendorRegistry)
            .where(VendorRegistry.org_id == ctx.org_id)
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
                VendorRegistry.org_id == ctx.org_id,
                VendorRegistry.vendor_slug == body.vendor_slug,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"Vendor slug '{body.vendor_slug}' already exists")

    row = VendorRegistry(
        org_id=ctx.org_id,
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
    if not row or row.org_id != ctx.org_id:
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
    if not row or row.org_id != ctx.org_id:
        raise HTTPException(404, "Vendor not found")
    await db.delete(row)
    await db.flush()
