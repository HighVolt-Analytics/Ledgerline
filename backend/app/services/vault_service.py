"""Vault tree and blob migration — single source of truth for folder layout."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.schemas.vault import VaultFileEntry, VaultMigrateResponse, VaultTreeNode, VaultTreeResponse
from app.services import blob_storage
from app.services.audit_service import log_event
from app.services.file_storage import has_stored_path
from app.services.invoice_evaluation_service import load_config_for_tenant
from app.services.tenant_context_service import get_tenant_slug
from app.services.vault_invoice_paths import vault_document_type_folder_for_invoice
from app.services.vault_migrate import migrate_org_blobs_to_vault
from app.services.vault_paths import (
    build_vault_tree,
    build_virtual_path,
    filename_from_stored,
    vault_book_folder,
    vault_file_name,
    vault_month,
    vault_tenant_folder,
    vault_po_reference_label,
    vault_vendor_folder,
    vault_year,
)


async def get_vault_tree_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: int,
) -> VaultTreeResponse:
    """Return org → book → [document_type →] vendor → year → month tree for stored invoice files."""
    org = await session.get(Tenant, tenant_id)
    tenant_slug = await get_tenant_slug(session, tenant_id)
    tenant_name = org.name if org else None
    org_folder = vault_tenant_folder(tenant_slug, tenant_name)
    config = await load_config_for_tenant(session, tenant_id)
    document_types = list(config.document_types)

    rows = (
        await session.execute(
            select(Invoice).where(
                Invoice.tenant_id == tenant_id,
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
        book = vault_book_folder(inv.route_target)
        document_type = vault_document_type_folder_for_invoice(inv, document_types)
        vendor = vault_vendor_folder(inv.vendor, inv.storage_vendor_slug)
        year = vault_year(inv.invoice_date)
        month = vault_month(inv.invoice_date)
        po_label = vault_po_reference_label(inv.po_reference)
        file_name = vault_file_name(
            inv.invoice_no,
            inv.id,
            inv.invoice_date,
            original,
            purchase_document_type=inv.purchase_document_type,
            po_reference=inv.po_reference,
        )
        virtual_path = build_virtual_path(
            tenant_slug,
            tenant_name=tenant_name,
            route_target=inv.route_target,
            vendor_name=inv.vendor,
            storage_vendor_slug=inv.storage_vendor_slug,
            invoice_id=inv.id,
            invoice_no=inv.invoice_no,
            invoice_date=inv.invoice_date,
            original_filename=original,
            po_reference=inv.po_reference,
            purchase_document_type=inv.purchase_document_type,
            document_type_code=inv.document_type_code,
            document_type_folder=document_type,
        )
        has_file = has_stored_path(inv.raw_file_path)
        entry = {
            "org": org_folder,
            "book": book,
            "document_type": document_type or "",
            "vendor": vendor,
            "year": year,
            "month": month,
            "po_folder": po_label or "",
        }
        files.append(
            VaultFileEntry(
                invoice_id=inv.id,
                org=org_folder,
                book=book,
                document_type=document_type,
                vendor=vendor,
                year=year,
                month=month,
                po_folder=po_label,
                purchase_document_type=inv.purchase_document_type,
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


async def migrate_vault_for_tenant(
    session: AsyncSession,
    tenant_id: int,
) -> VaultMigrateResponse:
    """Relocate this org's invoice blobs into the vault folder layout."""
    if not blob_storage.is_blob_enabled():
        return VaultMigrateResponse(moved=0, skipped=0, blob_enabled=False)

    moved, skipped = await migrate_org_blobs_to_vault(session, tenant_id)
    await log_event(
        session,
        "vault_migrated",
        detail={"moved": moved, "skipped": skipped, "tenant_id": tenant_id},
    )
    return VaultMigrateResponse(moved=moved, skipped=skipped, blob_enabled=True)
