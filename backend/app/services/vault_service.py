"""Vault tree and blob migration — single source of truth for folder layout."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.organisation import Organisation
from app.schemas.vault import VaultFileEntry, VaultMigrateResponse, VaultTreeNode, VaultTreeResponse
from app.services import blob_storage
from app.services.audit_service import log_event
from app.services.file_storage import has_stored_path
from app.services.org_context import get_org_slug
from app.services.vault_migrate import migrate_org_blobs_to_vault
from app.services.vault_paths import (
    build_vault_tree,
    build_virtual_path,
    filename_from_stored,
    vault_file_name,
    vault_month,
    vault_org_folder,
    vault_vendor_folder,
    vault_year,
)


async def get_vault_tree_for_org(
    session: AsyncSession,
    *,
    org_id: int,
) -> VaultTreeResponse:
    """Return org → vendor → year → month tree for stored invoice files."""
    org = await session.get(Organisation, org_id)
    org_slug = await get_org_slug(session, org_id)
    org_name = org.name if org else None
    org_folder = vault_org_folder(org_slug, org_name)

    rows = (
        await session.execute(
            select(Invoice).where(
                Invoice.org_id == org_id,
                Invoice.status != InvoiceStatus.DUPLICATE_SKIPPED,
                Invoice.status != InvoiceStatus.REJECTED,
                Invoice.raw_file_path.isnot(None),
            )
        )
    ).scalars().all()

    entries: list[dict] = []
    files: list[VaultFileEntry] = []

    for inv in rows:
        original = filename_from_stored(inv.raw_file_path)
        vendor = vault_vendor_folder(inv.vendor, inv.storage_vendor_slug)
        year = vault_year(inv.invoice_date)
        month = vault_month(inv.invoice_date)
        file_name = vault_file_name(
            inv.invoice_no, inv.id, inv.invoice_date, original
        )
        virtual_path = build_virtual_path(
            org_slug,
            org_name=org_name,
            vendor_name=inv.vendor,
            storage_vendor_slug=inv.storage_vendor_slug,
            invoice_id=inv.id,
            invoice_no=inv.invoice_no,
            invoice_date=inv.invoice_date,
            original_filename=original,
        )
        has_file = has_stored_path(inv.raw_file_path)
        entry = {
            "org": org_folder,
            "vendor": vendor,
            "year": year,
            "month": month,
        }
        files.append(
            VaultFileEntry(
                invoice_id=inv.id,
                org=org_folder,
                vendor=vendor,
                year=year,
                month=month,
                file_name=file_name,
                virtual_path=virtual_path,
                blob_path=inv.raw_file_path,
                has_stored_file=has_file,
            )
        )
        if has_file:
            entries.append(entry)

    tree = [VaultTreeNode.model_validate(node) for node in build_vault_tree(entries)]
    return VaultTreeResponse(
        tree=tree,
        files=files,
        blob_enabled=blob_storage.is_blob_enabled(),
    )


async def migrate_vault_for_org(
    session: AsyncSession,
    org_id: int,
) -> VaultMigrateResponse:
    """Relocate this org's invoice blobs into the vault folder layout."""
    if not blob_storage.is_blob_enabled():
        return VaultMigrateResponse(moved=0, skipped=0, blob_enabled=False)

    moved, skipped = await migrate_org_blobs_to_vault(session, org_id)
    await log_event(
        session,
        "vault_migrated",
        detail={"moved": moved, "skipped": skipped, "org_id": org_id},
    )
    return VaultMigrateResponse(moved=moved, skipped=skipped, blob_enabled=True)
