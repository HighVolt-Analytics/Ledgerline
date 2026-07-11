"""Vendor registry CRUD — storage slug routing table."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vendor import VendorRegistry
from app.schemas.vendor import VendorCreate, VendorResponse, VendorUpdate
from app.services.master_data.party_coa_subledger_service import ensure_vendor_party_coa_sub_ledger
from app.tenant_scoped import get_for_tenant


async def list_vendor_registry(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> list[VendorResponse]:
    rows = (
        await db.execute(
            select(VendorRegistry)
            .where(VendorRegistry.tenant_id == tenant_id)
            .order_by(VendorRegistry.vendor_name)
        )
    ).scalars().all()
    return [VendorResponse.model_validate(r) for r in rows]


async def create_vendor_registry(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    body: VendorCreate,
) -> VendorResponse:
    existing = (
        await db.execute(
            select(VendorRegistry).where(
                VendorRegistry.tenant_id == tenant_id,
                VendorRegistry.vendor_slug == body.vendor_slug,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise ValueError(f"Vendor slug '{body.vendor_slug}' already exists")

    row = VendorRegistry(
        tenant_id=tenant_id,
        vendor_slug=body.vendor_slug,
        vendor_name=body.vendor_name,
        sender_pattern=body.sender_pattern,
        abn=body.abn,
        approved=body.approved,
    )
    db.add(row)
    await db.flush()
    await ensure_vendor_party_coa_sub_ledger(
        db,
        tenant_id,
        slug=row.vendor_slug,
        vendor_name=row.vendor_name,
    )
    return VendorResponse.model_validate(row)


async def update_vendor_registry(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    vendor_id: int,
    body: VendorUpdate,
) -> VendorResponse:
    row = await get_for_tenant(db, VendorRegistry, vendor_id, tenant_id)
    if not row:
        raise LookupError("Vendor not found")

    if body.vendor_name is not None:
        row.vendor_name = body.vendor_name
    if body.sender_pattern is not None:
        row.sender_pattern = body.sender_pattern
    if body.abn is not None:
        row.abn = body.abn
    if body.approved is not None:
        row.approved = body.approved

    await db.flush()
    await ensure_vendor_party_coa_sub_ledger(
        db,
        tenant_id,
        slug=row.vendor_slug,
        vendor_name=row.vendor_name,
    )
    return VendorResponse.model_validate(row)


async def delete_vendor_registry(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    vendor_id: int,
) -> None:
    row = await get_for_tenant(db, VendorRegistry, vendor_id, tenant_id)
    if not row:
        raise LookupError("Vendor not found")
    await db.delete(row)
    await db.flush()
