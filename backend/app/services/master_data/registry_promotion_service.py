"""Sync capture registry rows when pending vendors/customers are promoted."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import CustomerRegistry
from app.models.invoice import Invoice
from app.models.vendor import VendorRegistry
from app.services.master_data.party_coa_subledger_service import (
    ensure_customer_party_coa_sub_ledger,
    ensure_vendor_party_coa_sub_ledger,
)
from app.services.master_data.vendor_resolver import UNKNOWN_SLUG, slugify_vendor_name


async def _sender_from_source_invoice(
    db: AsyncSession,
    source_invoice_id: int | None,
) -> str | None:
    if source_invoice_id is None:
        return None
    inv = await db.get(Invoice, source_invoice_id)
    if inv is None:
        return None
    sender = (inv.email_sender or "").strip()
    return sender or None


async def upsert_vendor_registry_from_promotion(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    name: str,
    abn: str | None = None,
    sender_pattern: str | None = None,
) -> None:
    """Create or update vendor_registry when a master is promoted (best-effort)."""
    slug = slugify_vendor_name(name)
    if slug == UNKNOWN_SLUG:
        return

    row = (
        await db.execute(
            select(VendorRegistry).where(
                VendorRegistry.tenant_id == tenant_id,
                VendorRegistry.vendor_slug == slug,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        pattern = (sender_pattern or "").strip()
        if not pattern:
            return
        db.add(
            VendorRegistry(
                tenant_id=tenant_id,
                vendor_slug=slug,
                vendor_name=name.strip(),
                sender_pattern=pattern,
                abn=(abn or "").strip() or None,
                approved=False,
            )
        )
        await db.flush()
        await ensure_vendor_party_coa_sub_ledger(
            db,
            tenant_id,
            slug=slug,
            vendor_name=name.strip(),
        )
        return

    if name.strip() and row.vendor_name.strip().lower() != name.strip().lower():
        row.vendor_name = name.strip()
    if abn and abn.strip():
        row.abn = abn.strip()
    pattern = (sender_pattern or "").strip()
    if pattern and row.sender_pattern.strip().lower() != pattern.lower():
        row.sender_pattern = pattern
    await db.flush()
    await ensure_vendor_party_coa_sub_ledger(
        db,
        tenant_id,
        slug=row.vendor_slug,
        vendor_name=row.vendor_name,
    )


async def upsert_customer_registry_from_promotion(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    name: str,
    abn: str | None = None,
    sender_pattern: str | None = None,
) -> None:
    """Create or update customer_registry when a master is promoted (best-effort)."""
    slug = slugify_vendor_name(name)
    if slug == UNKNOWN_SLUG:
        return

    row = (
        await db.execute(
            select(CustomerRegistry).where(
                CustomerRegistry.tenant_id == tenant_id,
                CustomerRegistry.customer_slug == slug,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        pattern = (sender_pattern or "").strip()
        if not pattern:
            return
        db.add(
            CustomerRegistry(
                tenant_id=tenant_id,
                customer_slug=slug,
                customer_name=name.strip(),
                sender_pattern=pattern,
                abn=(abn or "").strip() or None,
                approved=False,
            )
        )
        await db.flush()
        await ensure_customer_party_coa_sub_ledger(
            db,
            tenant_id,
            slug=slug,
            customer_name=name.strip(),
        )
        return

    if name.strip() and row.customer_name.strip().lower() != name.strip().lower():
        row.customer_name = name.strip()
    if abn and abn.strip():
        row.abn = abn.strip()
    pattern = (sender_pattern or "").strip()
    if pattern and row.sender_pattern.strip().lower() != pattern.lower():
        row.sender_pattern = pattern
    await db.flush()
    await ensure_customer_party_coa_sub_ledger(
        db,
        tenant_id,
        slug=row.customer_slug,
        customer_name=row.customer_name,
    )


async def sync_vendor_registry_after_promotion(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    name: str,
    abn: str | None,
    source_invoice_id: int | None,
) -> None:
    sender = await _sender_from_source_invoice(db, source_invoice_id)
    await upsert_vendor_registry_from_promotion(
        db,
        tenant_id=tenant_id,
        name=name,
        abn=abn,
        sender_pattern=sender,
    )


async def sync_customer_registry_after_promotion(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    name: str,
    abn: str | None,
    source_invoice_id: int | None,
) -> None:
    sender = await _sender_from_source_invoice(db, source_invoice_id)
    await upsert_customer_registry_from_promotion(
        db,
        tenant_id=tenant_id,
        name=name,
        abn=abn,
        sender_pattern=sender,
    )
