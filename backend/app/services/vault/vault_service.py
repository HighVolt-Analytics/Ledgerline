"""Vault tree and blob migration — single source of truth for folder layout."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, noload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.schemas.vault import (
    VaultDocumentSetCard,
    VaultDocumentSetInvoice,
    VaultDocumentSetsResponse,
    VaultFileEntry,
    VaultFilesResponse,
    VaultMigrateResponse,
    VaultTreeNode,
    VaultTreeResponse,
)
from app.services.shared import blob_storage
from app.services.audit.audit_service import log_event
from app.services.shared.file_storage import has_stored_path
from app.services.invoice.invoice_evaluation_service import load_posting_config_for_tenant
from app.services.tenant.tenant_context_service import get_tenant_slug
from app.services.vault.vault_invoice_paths import vault_document_type_folder_for_invoice
from app.services.vault.vault_migrate import migrate_org_blobs_to_vault
from app.services.vault.vault_paths import (
    ROUTE_VAULT,
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

VAULT_PAGE_FILE_LIMIT = 50
_VAULT_SET_INVOICE_LIMIT = 50

_VAULT_INVOICE_LOAD = (
    load_only(
        Invoice.id,
        Invoice.tenant_id,
        Invoice.vendor,
        Invoice.storage_vendor_slug,
        Invoice.invoice_no,
        Invoice.invoice_date,
        Invoice.route_target,
        Invoice.raw_file_path,
        Invoice.purchase_document_type,
        Invoice.po_reference,
        Invoice.document_type_code,
        Invoice.document_heading,
        Invoice.extracted_fields,
        Invoice.document_ref,
        Invoice.total,
        Invoice.currency,
        Invoice.capture_source,
        Invoice.status,
    ),
    noload(Invoice.line_items),
    noload(Invoice.journal_entries),
)

_VAULT_SET_INVOICE_LOAD = (
    load_only(
        Invoice.id,
        Invoice.vendor,
        Invoice.invoice_no,
        Invoice.invoice_date,
        Invoice.document_ref,
        Invoice.total,
        Invoice.currency,
        Invoice.capture_source,
        Invoice.document_heading,
        Invoice.document_type_code,
        Invoice.purchase_document_type,
        Invoice.po_reference,
        Invoice.route_target,
        Invoice.status,
    ),
    noload(Invoice.line_items),
    noload(Invoice.journal_entries),
)


async def _load_vault_invoices(session: AsyncSession, *, tenant_id: Any) -> list[Invoice]:
    rows = (
        await session.execute(
            select(Invoice)
            .options(*_VAULT_INVOICE_LOAD)
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.status != InvoiceStatus.DUPLICATE_SKIPPED,
                Invoice.status != InvoiceStatus.REJECTED,
                Invoice.raw_file_path.isnot(None),
            )
        )
    ).scalars().all()
    return list(rows)


async def _tenant_folder_context(
    session: AsyncSession, *, tenant_id: Any
) -> tuple[str, str | None, str]:
    org = await session.get(Tenant, tenant_id)
    tenant_slug = await get_tenant_slug(session, tenant_id)
    tenant_name = org.name if org else None
    org_folder = vault_tenant_folder(tenant_slug, tenant_name)
    return tenant_slug, tenant_name, org_folder


def _file_entry_for_invoice(
    inv: Invoice,
    *,
    tenant_id: Any,
    tenant_slug: str,
    tenant_name: str | None,
    org_folder: str,
    document_types: list[Any],
) -> tuple[VaultFileEntry, dict[str, str] | None]:
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
        tenant_id,
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
    entry = VaultFileEntry(
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
        document_ref=inv.document_ref,
        invoice_no=inv.invoice_no,
        invoice_date=inv.invoice_date,
        total=inv.total,
        currency=inv.currency or "",
        capture_source=inv.capture_source,
        document_heading=inv.document_heading,
        document_type_code=inv.document_type_code,
    )
    tree_entry = None
    if has_file:
        tree_entry = {
            "org": org_folder,
            "book": book,
            "document_type": document_type or "",
            "vendor": vendor,
            "year": year,
            "month": month,
            "po_folder": po_label or "",
        }
    return entry, tree_entry


def _file_matches_filters(
    file: VaultFileEntry,
    *,
    invoice_id: int | None = None,
    org: str | None = None,
    book: str | None = None,
    document_type: str | None = None,
    vendor: str | None = None,
    year: str | None = None,
    month: str | None = None,
    po_folder: str | None = None,
) -> bool:
    if invoice_id is not None and file.invoice_id != invoice_id:
        return False
    if org and file.org != org:
        return False
    if book and file.book != book:
        return False
    if document_type and (file.document_type or "") != document_type:
        return False
    if vendor and file.vendor != vendor:
        return False
    if year and file.year != year:
        return False
    if month and file.month != month:
        return False
    if po_folder and (file.po_folder or "") != po_folder:
        return False
    return True


async def get_vault_tree_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: Any,
    include_files: bool = True,
    file_limit: int | None = None,
) -> VaultTreeResponse:
    """Return org → book → [document_type →] vendor → year → month tree for stored invoice files."""
    tenant_slug, tenant_name, org_folder = await _tenant_folder_context(
        session, tenant_id=tenant_id
    )
    config = await load_posting_config_for_tenant(session, tenant_id)
    document_types = list(config.document_types)
    rows = await _load_vault_invoices(session, tenant_id=tenant_id)

    entries: list[dict[str, str]] = []
    files: list[VaultFileEntry] = []
    for inv in rows:
        file_entry, tree_entry = _file_entry_for_invoice(
            inv,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            tenant_name=tenant_name,
            org_folder=org_folder,
            document_types=document_types,
        )
        files.append(file_entry)
        if tree_entry is not None:
            entries.append(tree_entry)

    tree = [VaultTreeNode.model_validate(node) for node in build_vault_tree(entries)]
    file_count = len(files)
    if not include_files:
        files = []
    elif file_limit is not None and file_limit >= 0:
        files = files[:file_limit]
    return VaultTreeResponse(
        tree=tree,
        files=files,
        blob_enabled=blob_storage.is_blob_enabled(),
        file_count=file_count,
    )


async def get_vault_files_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: Any,
    invoice_id: int | None = None,
    org: str | None = None,
    book: str | None = None,
    document_type: str | None = None,
    vendor: str | None = None,
    year: str | None = None,
    month: str | None = None,
    po_folder: str | None = None,
    limit: int = VAULT_PAGE_FILE_LIMIT,
) -> VaultFilesResponse:
    """Return files for a folder selection (or a single invoice) without the full tree."""
    tenant_slug, tenant_name, org_folder = await _tenant_folder_context(
        session, tenant_id=tenant_id
    )
    config = await load_posting_config_for_tenant(session, tenant_id)
    document_types = list(config.document_types)
    rows = await _load_vault_invoices(session, tenant_id=tenant_id)

    matched: list[VaultFileEntry] = []
    for inv in rows:
        file_entry, _tree_entry = _file_entry_for_invoice(
            inv,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            tenant_name=tenant_name,
            org_folder=org_folder,
            document_types=document_types,
        )
        if _file_matches_filters(
            file_entry,
            invoice_id=invoice_id,
            org=org,
            book=book,
            document_type=document_type,
            vendor=vendor,
            year=year,
            month=month,
            po_folder=po_folder,
        ):
            matched.append(file_entry)

    return VaultFilesResponse(
        files=matched[: max(limit, 0)],
        count=len(matched),
    )


def _invoice_matches_doc_set(invoice_no: str | None, po_reference: str | None, pattern: str) -> bool:
    needle = (pattern or "").strip().lower()
    if not needle:
        return False
    po = (po_reference or "").lower()
    doc = (invoice_no or "").lower()
    return po == needle or needle in po or needle in doc


def _document_set_invoice(inv: Invoice) -> VaultDocumentSetInvoice:
    return VaultDocumentSetInvoice(
        id=inv.id,
        vendor=inv.vendor,
        invoice_no=inv.invoice_no,
        invoice_date=inv.invoice_date,
        document_ref=inv.document_ref,
        total=inv.total,
        currency=inv.currency or "",
        capture_source=inv.capture_source,
        document_heading=inv.document_heading,
        document_type_code=inv.document_type_code,
        purchase_document_type=inv.purchase_document_type,
    )


async def get_vault_document_sets_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: Any,
    invoice_limit: int = _VAULT_SET_INVOICE_LIMIT,
) -> VaultDocumentSetsResponse:
    """Document-set cards with tenant-wide match counts and a capped invoice list."""
    config = await load_posting_config_for_tenant(session, tenant_id)
    sets = list(config.document_sets)
    rows = (
        await session.execute(
            select(Invoice)
            .options(*_VAULT_SET_INVOICE_LOAD)
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.route_target == ROUTE_VAULT,
                Invoice.status != InvoiceStatus.DUPLICATE_SKIPPED,
                Invoice.status != InvoiceStatus.REJECTED,
            )
        )
    ).scalars().all()

    assigned: set[int] = set()
    cards: list[VaultDocumentSetCard] = []
    cap = max(invoice_limit, 0)
    for rule in sets:
        matched: list[Invoice] = [
            inv
            for inv in rows
            if _invoice_matches_doc_set(inv.invoice_no, inv.po_reference, rule.pattern)
        ]
        if rule.isolated:
            matched = [inv for inv in matched if inv.id not in assigned]
            assigned.update(inv.id for inv in matched)
        cards.append(
            VaultDocumentSetCard(
                id=rule.id,
                pattern=rule.pattern,
                set_name=rule.set_name,
                isolated=rule.isolated,
                match_count=len(matched),
                invoices=[_document_set_invoice(inv) for inv in matched[:cap]],
            )
        )
    return VaultDocumentSetsResponse(sets=cards)


async def migrate_vault_for_tenant(
    session: AsyncSession,
    tenant_id: Any,
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
