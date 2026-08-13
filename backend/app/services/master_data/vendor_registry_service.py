"""Vendor registry CRUD — storage slug routing table."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.vendor import VendorRegistry
from app.schemas.vendor import VendorActivityRow, VendorCreate, VendorResponse, VendorUpdate
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


async def list_vendor_activity(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> list[VendorActivityRow]:
    """Aggregate invoice stats by vendor name — avoids loading the full register."""
    rows = (
        await db.execute(
            select(
                Invoice.vendor,
                func.count(Invoice.id),
                func.max(Invoice.email_sender),
                func.max(Invoice.account_name),
            )
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.vendor.isnot(None),
                Invoice.vendor != "",
            )
            .group_by(Invoice.vendor)
        )
    ).all()

    totals = (
        await db.execute(
            select(Invoice.vendor, Invoice.currency, func.sum(Invoice.total))
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.vendor.isnot(None),
                Invoice.vendor != "",
                Invoice.total.isnot(None),
            )
            .group_by(Invoice.vendor, Invoice.currency)
        )
    ).all()
    by_vendor_currency: dict[str, dict[str, float]] = {}
    for vendor, currency, total in totals:
        key = (vendor or "").strip()
        if not key:
            continue
        code = (currency or "").strip().upper() or "—"
        bucket = by_vendor_currency.setdefault(key, {})
        bucket[code] = bucket.get(code, 0.0) + float(total or 0)

    net_rows = (
        await db.execute(
            select(
                Invoice.vendor,
                Invoice.invoice_date,
                Invoice.due_date,
            ).where(
                Invoice.tenant_id == tenant_id,
                Invoice.vendor.isnot(None),
                Invoice.invoice_date.isnot(None),
                Invoice.due_date.isnot(None),
            )
        )
    ).all()
    net_by_vendor: dict[str, list[int]] = {}
    for vendor, invoice_date, due_date in net_rows:
        key = (vendor or "").strip()
        if not key or invoice_date is None or due_date is None:
            continue
        days = (due_date - invoice_date).days
        if days >= 0:
            net_by_vendor.setdefault(key, []).append(days)

    out: list[VendorActivityRow] = []
    for vendor, count, email, account in rows:
        key = (vendor or "").strip()
        if not key:
            continue
        nets = net_by_vendor.get(key, [])
        net_days = round(sum(nets) / len(nets)) if nets else None
        out.append(
            VendorActivityRow(
                vendor=key,
                invoice_count=int(count or 0),
                by_currency=by_vendor_currency.get(key, {}),
                email=email,
                default_account=account or "Suspense Account",
                net_days=net_days,
            )
        )
    out.sort(key=lambda row: row.vendor.lower())
    return out
