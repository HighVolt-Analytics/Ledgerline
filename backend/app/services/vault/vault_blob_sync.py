"""Keep stored invoice blobs aligned with vault routing (route_target, vendor, book)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.invoice import Invoice
from app.models.tenant import Tenant
from app.services.audit.audit_service import log_event
from app.services.shared.file_storage import relocate_invoice_pdf
from app.services.invoice.invoice_evaluation_service import load_config_for_tenant
from app.services.tenant.tenant_storage_paths import blob_name_from_stored
from app.services.vault.vault_invoice_paths import vault_document_type_titles_for_invoice
from app.services.vault.vault_paths import (
    build_vault_blob_name,
    filename_from_stored,
    strip_org_segment_from_blob_path,
    vault_book_folder,
)
from app.services.master_data.vendor_resolver import (
    UNKNOWN_SLUG,
    is_valid_storage_slug,
    resolve_storage_slug_for_parsed_vendor,
)


def blob_layout_matches_invoice(
    stored_path: str | None,
    expected_blob_name: str,
) -> bool:
    current = blob_name_from_stored(stored_path)
    if not current:
        return False
    expected = expected_blob_name.strip().lstrip("/")
    if current == expected:
        return True
    return strip_org_segment_from_blob_path(current) == expected


def blob_book_segment(stored_path: str | None) -> str | None:
    name = blob_name_from_stored(stored_path)
    if not name:
        return None
    parts = name.split("/")
    try:
        idx = parts.index("invoice")
    except ValueError:
        return None
    if idx + 1 >= len(parts):
        return None
    return parts[idx + 1]


async def sync_invoice_blob_path(
    session: AsyncSession,
    invoice: Invoice,
    *,
    parsed_vendor: str | None = None,
) -> bool:
    """Relocate stored PDF to match current route/vendor vault layout. Returns True when moved."""
    if not invoice.raw_file_path or not invoice.file_hash:
        return False

    settings = get_settings()
    if settings.blob_auto_relocate_unknown:
        new_slug = await resolve_storage_slug_for_parsed_vendor(
            session, parsed_vendor or invoice.vendor, tenant_id=invoice.tenant_id
        )
        old_slug = invoice.storage_vendor_slug or UNKNOWN_SLUG
        if new_slug != old_slug:
            if new_slug != UNKNOWN_SLUG or not is_valid_storage_slug(old_slug):
                invoice.storage_vendor_slug = new_slug

    org = await session.get(Tenant, invoice.tenant_id)
    tenant_slug = org.slug if org else settings.default_tenant_slug
    tenant_name = org.name if org else None
    filename = filename_from_stored(invoice.raw_file_path)
    config = await load_config_for_tenant(session, invoice.tenant_id)
    from app.services.vault.vault_invoice_paths import vault_document_type_folder_for_invoice

    document_type_folder = vault_document_type_folder_for_invoice(
        invoice, list(config.document_types)
    )
    short_title, title = vault_document_type_titles_for_invoice(
        invoice, list(config.document_types)
    )

    expected = build_vault_blob_name(
        invoice.tenant_id,
        tenant_slug,
        tenant_name=tenant_name,
        route_target=invoice.route_target,
        vendor_name=invoice.vendor or parsed_vendor,
        storage_vendor_slug=invoice.storage_vendor_slug,
        invoice_id=invoice.id,
        invoice_no=invoice.invoice_no,
        invoice_date=invoice.invoice_date,
        original_filename=filename,
        po_reference=invoice.po_reference,
        purchase_document_type=invoice.purchase_document_type,
        document_type_code=invoice.document_type_code,
        document_type_short_title=short_title,
        document_type_title=title,
        document_type_folder=document_type_folder,
    )

    if blob_layout_matches_invoice(invoice.raw_file_path, expected):
        return False

    new_path = relocate_invoice_pdf(
        invoice.raw_file_path,
        invoice.tenant_id,
        tenant_slug,
        invoice.storage_vendor_slug or UNKNOWN_SLUG,
        invoice.id,
        invoice.file_hash,
        filename,
        tenant_name=tenant_name,
        vendor_name=invoice.vendor or parsed_vendor,
        invoice_no=invoice.invoice_no,
        invoice_date=invoice.invoice_date,
        route_target=invoice.route_target,
        po_reference=invoice.po_reference,
        purchase_document_type=invoice.purchase_document_type,
        document_type_code=invoice.document_type_code,
        document_type_short_title=short_title,
        document_type_title=title,
        document_type_folder=document_type_folder,
    )
    if new_path == invoice.raw_file_path:
        return False

    old_path = invoice.raw_file_path
    invoice.raw_file_path = new_path
    await log_event(
        session,
        "blob_relocated",
        invoice_id=invoice.id,
        detail={
            "vendor_slug": invoice.storage_vendor_slug,
            "from_path": old_path,
            "to_path": new_path,
            "reason": "vault_layout_sync",
        },
    )
    return True


def route_target_matches_blob(invoice: Invoice) -> bool:
    if not invoice.raw_file_path:
        return True
    book = blob_book_segment(invoice.raw_file_path)
    if not book:
        return True
    return book == vault_book_folder(invoice.route_target)
