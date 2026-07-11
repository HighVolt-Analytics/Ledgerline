"""Customer registry CRUD — storage slug routing table."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import CustomerRegistry
from app.schemas.customer import CustomerCreate, CustomerResponse, CustomerUpdate
from app.services.master_data.party_coa_subledger_service import ensure_customer_party_coa_sub_ledger
from app.services.master_data.vendor_resolver import slugify_vendor_name
from app.tenant_scoped import get_for_tenant


async def list_customer_registry(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> list[CustomerResponse]:
    rows = (
        await db.execute(
            select(CustomerRegistry)
            .where(CustomerRegistry.tenant_id == tenant_id)
            .order_by(CustomerRegistry.customer_name)
        )
    ).scalars().all()
    return [CustomerResponse.model_validate(r) for r in rows]


async def create_customer_registry(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    body: CustomerCreate,
) -> CustomerResponse:
    existing = (
        await db.execute(
            select(CustomerRegistry).where(
                CustomerRegistry.tenant_id == tenant_id,
                CustomerRegistry.customer_slug == body.customer_slug,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise ValueError(f"Customer slug '{body.customer_slug}' already exists")

    row = CustomerRegistry(
        tenant_id=tenant_id,
        customer_slug=body.customer_slug,
        customer_name=body.customer_name,
        sender_pattern=body.sender_pattern,
        abn=body.abn,
        approved=body.approved,
    )
    db.add(row)
    await db.flush()
    await ensure_customer_party_coa_sub_ledger(
        db,
        tenant_id,
        slug=row.customer_slug,
        customer_name=row.customer_name,
    )
    return CustomerResponse.model_validate(row)


async def update_customer_registry(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    customer_id: int,
    body: CustomerUpdate,
) -> CustomerResponse:
    row = await get_for_tenant(db, CustomerRegistry, customer_id, tenant_id)
    if not row:
        raise LookupError("Customer not found")

    if body.customer_name is not None:
        row.customer_name = body.customer_name
    if body.sender_pattern is not None:
        row.sender_pattern = body.sender_pattern
    if body.abn is not None:
        row.abn = body.abn
    if body.approved is not None:
        row.approved = body.approved

    await db.flush()
    await ensure_customer_party_coa_sub_ledger(
        db,
        tenant_id,
        slug=row.customer_slug,
        customer_name=row.customer_name,
    )
    return CustomerResponse.model_validate(row)


async def delete_customer_registry(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    customer_id: int,
) -> None:
    row = await get_for_tenant(db, CustomerRegistry, customer_id, tenant_id)
    if not row:
        raise LookupError("Customer not found")
    await db.delete(row)
    await db.flush()


async def resolve_customer_registry_id_for_invoice(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    customer_name: str | None,
    storage_slug: str | None = None,
) -> int | None:
    """Best-effort customer registry lookup for AR collections."""
    slug = (storage_slug or "").strip().lower()
    if slug:
        row = (
            await db.execute(
                select(CustomerRegistry).where(
                    CustomerRegistry.tenant_id == tenant_id,
                    CustomerRegistry.customer_slug == slug,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            return row.id

    name = (customer_name or "").strip().lower()
    if name:
        rows = (
            await db.execute(
                select(CustomerRegistry).where(CustomerRegistry.tenant_id == tenant_id)
            )
        ).scalars().all()
        for row in rows:
            row_name = row.customer_name.strip().lower()
            if row_name == name:
                return row.id
            row_slug = row.customer_slug.replace("-", " ")
            if row_slug == name or name in row_name or row_name in name:
                return row.id
        derived_slug = slugify_vendor_name(customer_name or "")
        if derived_slug:
            row = (
                await db.execute(
                    select(CustomerRegistry).where(
                        CustomerRegistry.tenant_id == tenant_id,
                        CustomerRegistry.customer_slug == derived_slug,
                    )
                )
            ).scalar_one_or_none()
            if row is not None:
                return row.id
    return None
