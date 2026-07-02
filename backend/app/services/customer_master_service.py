"""Customer master CRUD — rule book detection source of truth."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer_master import CustomerMasterRecord
from app.schemas.customer import CustomerMasterCreate, CustomerMasterResponse, CustomerMasterUpdate
from app.services.rule_book_mapper import clear_classification_config_cache
from app.tenant_scoped import coerce_tenant_uuid


def _tenant_id(tenant_id: uuid.UUID | int | str) -> uuid.UUID:
    resolved = coerce_tenant_uuid(tenant_id)
    if resolved is None:
        raise ValueError("Invalid tenant_id")
    return resolved


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:80] or "customer"


def _new_master_id(prefix: str, name: str) -> str:
    base = f"{prefix}-{_slugify(name)}"
    return f"{base}-{uuid.uuid4().hex[:6]}"


def _normalize_abn(abn: str | None) -> str:
    if not abn:
        return ""
    return re.sub(r"\D", "", abn.strip())[:11]


def customer_record_to_schema(row: CustomerMasterRecord) -> CustomerMasterResponse:
    return CustomerMasterResponse(
        db_id=row.id,
        id=row.master_id,
        name=row.name,
        aliases=row.aliases or [],
        abn=row.abn or "",
        billing_address=row.billing_address or {},
        default_ledger=row.default_ledger or "",
        default_sub_ledger=row.default_sub_ledger or "",
        payment_terms=row.payment_terms or "",
        status=row.status or "",
        registered_on=row.registered_on or "",
        total_revenue_ytd=row.total_revenue_ytd or 0,
        invoice_count=row.invoice_count or 0,
        match_confidence=row.match_confidence or 0,
    )


async def get_customer_master_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    master_id: str,
) -> CustomerMasterRecord | None:
    return (
        await db.execute(
            select(CustomerMasterRecord).where(
                CustomerMasterRecord.tenant_id == tenant_id,
                CustomerMasterRecord.master_id == master_id,
            )
        )
    ).scalar_one_or_none()


async def list_customer_masters(
    db: AsyncSession,
    tenant_id: uuid.UUID | int | str,
) -> list[CustomerMasterResponse]:
    tid = _tenant_id(tenant_id)
    rows = (
        await db.execute(
            select(CustomerMasterRecord)
            .where(CustomerMasterRecord.tenant_id == tid)
            .order_by(CustomerMasterRecord.name)
        )
    ).scalars().all()
    return [customer_record_to_schema(row) for row in rows]


async def count_customer_masters(
    db: AsyncSession,
    tenant_id: uuid.UUID | int | str,
) -> int:
    tid = _tenant_id(tenant_id)
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(CustomerMasterRecord)
                .where(CustomerMasterRecord.tenant_id == tid)
            )
        ).scalar_one()
    )


async def create_customer_master(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    body: CustomerMasterCreate,
) -> CustomerMasterResponse:
    master_id = body.master_id or _new_master_id("cm", body.name)
    existing = await get_customer_master_by_id(db, tenant_id, master_id)
    if existing:
        raise ValueError(f"Customer master id '{master_id}' already exists")

    row = CustomerMasterRecord(
        tenant_id=tenant_id,
        master_id=master_id,
        name=body.name,
        aliases=body.aliases,
        abn=_normalize_abn(body.abn),
        billing_address=body.billing_address.model_dump(),
        default_ledger=body.default_ledger,
        default_sub_ledger=body.default_sub_ledger,
        payment_terms=body.payment_terms,
        status=body.status,
        registered_on=body.registered_on,
        total_revenue_ytd=body.total_revenue_ytd,
        invoice_count=body.invoice_count,
        match_confidence=body.match_confidence,
    )
    db.add(row)
    await db.flush()
    clear_classification_config_cache()
    return customer_record_to_schema(row)


async def update_customer_master(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    master_id: str,
    body: CustomerMasterUpdate,
) -> CustomerMasterResponse:
    row = await get_customer_master_by_id(db, tenant_id, master_id)
    if not row:
        raise LookupError("Customer master not found")

    patch = body.model_dump(exclude_unset=True)
    if "abn" in patch and patch["abn"] is not None:
        patch["abn"] = _normalize_abn(patch["abn"])
    for key, value in patch.items():
        if key == "billing_address" and value is not None:
            if hasattr(value, "model_dump"):
                value = value.model_dump(exclude_none=True)
        setattr(row, key, value)
    await db.flush()
    clear_classification_config_cache()
    return customer_record_to_schema(row)


async def delete_customer_master(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    master_id: str,
) -> None:
    row = await get_customer_master_by_id(db, tenant_id, master_id)
    if not row:
        raise LookupError("Customer master not found")
    await db.delete(row)
    await db.flush()
    clear_classification_config_cache()
