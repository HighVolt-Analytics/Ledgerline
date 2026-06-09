"""Migrate invoice blobs to vault folder layout."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.organisation import Organisation
from app.services.file_storage import relocate_invoice_pdf
from app.services.vault_paths import filename_from_stored
from app.services.vendor_resolver import UNKNOWN_SLUG


async def migrate_org_blobs_to_vault(session: AsyncSession, org_id: int) -> tuple[int, int]:
    """Move stored files for an org into invoice/{org}/{vendor}/{year}/{month}/."""
    moved = 0
    skipped = 0
    org = await session.get(Organisation, org_id)
    if not org:
        return moved, skipped

    rows = (
        await session.execute(
            select(Invoice).where(
                Invoice.org_id == org_id,
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
        filename = filename_from_stored(old)
        new = relocate_invoice_pdf(
            old,
            org.slug,
            inv.storage_vendor_slug or UNKNOWN_SLUG,
            inv.id,
            inv.file_hash,
            filename,
            org_name=org.name,
            vendor_name=inv.vendor,
            invoice_no=inv.invoice_no,
            invoice_date=inv.invoice_date,
        )
        if new != old:
            inv.raw_file_path = new
            moved += 1
        else:
            skipped += 1

    return moved, skipped
