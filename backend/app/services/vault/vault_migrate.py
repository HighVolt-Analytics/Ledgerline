"""Migrate invoice blobs to vault folder layout."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.services.vault.vault_blob_sync import sync_invoice_blob_path


async def migrate_org_blobs_to_vault(session: AsyncSession, tenant_id: int) -> tuple[int, int]:
    """Move stored files for an org into invoice/{book}/[{dt}/]{vendor}/{year}/{month}/."""
    moved = 0
    skipped = 0
    org = await session.get(Tenant, tenant_id)
    if not org:
        return moved, skipped

    rows = (
        await session.execute(
            select(Invoice).where(
                Invoice.tenant_id == tenant_id,
                Invoice.status != InvoiceStatus.DUPLICATE_SKIPPED,
                Invoice.raw_file_path.isnot(None),
            )
        )
    ).scalars().all()

    for inv in rows:
        old = inv.raw_file_path
        if not old or not inv.file_hash:
            skipped += 1
            continue
        if await sync_invoice_blob_path(session, inv):
            moved += 1
        else:
            skipped += 1

    return moved, skipped
