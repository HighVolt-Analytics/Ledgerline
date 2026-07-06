"""Customer master CRUD — rule book detection source of truth."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer_master import CustomerMasterRecord
from app.models.pending_customer import PendingCustomer
from app.schemas.customer import CustomerMasterCreate, CustomerMasterResponse, CustomerMasterUpdate
from app.schemas.master_data import (
    PendingCustomerCreate,
    PendingCustomerPromote,
    PendingCustomerResponse,
)
from app.schemas.rule_book_config import BillingAddress
from app.services.rule_book.rule_book_mapper import clear_classification_config_cache
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


async def list_pending_customers(
    db: AsyncSession,
    tenant_id: uuid.UUID | int | str,
) -> list[PendingCustomerResponse]:
    tid = _tenant_id(tenant_id)
    await _dismiss_pending_customers_matching_masters(db, tid)
    rows = (
        await db.execute(
            select(PendingCustomer)
            .where(
                PendingCustomer.tenant_id == tid,
                PendingCustomer.status == "pending",
            )
            .order_by(PendingCustomer.created_at.desc())
        )
    ).scalars().all()
    return [PendingCustomerResponse.model_validate(row) for row in rows]


async def _dismiss_pending_customers_matching_masters(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> None:
    from app.services.master_data.vendor_detection import find_matching_customer_master

    masters = await list_customer_masters(db, tenant_id)
    pending = (
        await db.execute(
            select(PendingCustomer).where(
                PendingCustomer.tenant_id == tenant_id,
                PendingCustomer.status == "pending",
            )
        )
    ).scalars().all()
    changed = False
    for row in pending:
        if find_matching_customer_master(row.detected_name, row.detected_abn, masters):
            row.status = "dismissed"
            row.resolved_at = datetime.now(UTC)
            changed = True
    if changed:
        await db.flush()


async def create_pending_customer(
    db: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    body: PendingCustomerCreate,
) -> PendingCustomerResponse:
    from app.services.master_data.vendor_detection import find_matching_customer_master

    tid = _tenant_id(tenant_id)
    masters = await list_customer_masters(db, tid)
    if find_matching_customer_master(body.detected_name, body.detected_abn, masters):
        raise ValueError("Customer already registered in master data")

    existing = (
        await db.execute(
            select(PendingCustomer).where(
                PendingCustomer.tenant_id == tid,
                PendingCustomer.status == "pending",
            )
        )
    ).scalars().all()
    name_key = body.detected_name.strip().lower()
    for row in existing:
        if row.detected_name.strip().lower() == name_key:
            return PendingCustomerResponse.model_validate(row)

    row = PendingCustomer(
        tenant_id=tid,
        detected_name=body.detected_name,
        detected_abn=body.detected_abn,
        detected_address=body.detected_address,
        source_invoice_id=body.source_invoice_id,
        confidence=body.confidence,
        status="pending",
    )
    db.add(row)
    await db.flush()
    return PendingCustomerResponse.model_validate(row)


async def dismiss_pending_customer(
    db: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    pending_id: int,
) -> None:
    tid = _tenant_id(tenant_id)
    row = await db.get(PendingCustomer, pending_id)
    if not row or row.tenant_id != tid:
        raise LookupError("Pending customer not found")
    row.status = "dismissed"
    row.resolved_at = datetime.now(UTC)
    await db.flush()


async def promote_pending_customer(
    db: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    pending_id: int,
    body: PendingCustomerPromote,
) -> CustomerMasterResponse:
    tid = _tenant_id(tenant_id)
    row = await db.get(PendingCustomer, pending_id)
    if not row or row.tenant_id != tid or row.status != "pending":
        raise LookupError("Pending customer not found")

    from app.services.master_data.vendor_detection import find_matching_customer_master

    masters = await list_customer_masters(db, tid)
    existing = find_matching_customer_master(row.detected_name, row.detected_abn, masters)
    if existing is not None:
        row.status = "promoted"
        row.promoted_master_id = existing.id
        row.resolved_at = datetime.now(UTC)
        await db.flush()
        from app.services.master_data.customer_hold_service import release_invoices_after_customer_promotion

        await release_invoices_after_customer_promotion(
            db,
            tid,
            customer_name=existing.name,
            source_invoice_id=row.source_invoice_id,
        )
        return existing

    name = body.name or row.detected_name
    master_id = body.master_id or _new_master_id("cm", name)
    customer = await create_customer_master(
        db,
        tid,
        CustomerMasterCreate(
            master_id=master_id,
            name=name,
            abn=body.abn or (row.detected_abn or ""),
            default_ledger=body.default_ledger,
            status=body.status,
            match_confidence=row.confidence,
            billing_address=BillingAddress(street=row.detected_address or ""),
        ),
    )
    row.status = "promoted"
    row.promoted_master_id = customer.id
    row.resolved_at = datetime.now(UTC)
    await db.flush()

    from app.services.master_data.customer_hold_service import release_invoices_after_customer_promotion

    await release_invoices_after_customer_promotion(
        db,
        tid,
        customer_name=name,
        source_invoice_id=row.source_invoice_id,
    )
    return customer
