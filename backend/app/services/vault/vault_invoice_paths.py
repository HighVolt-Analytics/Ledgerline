"""Resolve vault folder segments from invoice + document-type catalogue."""

from __future__ import annotations

from app.models.invoice import Invoice
from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_playbook_service import resolve_definition_for_invoice
from app.services.invoice.vision_header_extract import CANONICAL_DOCUMENT_TYPE_KEY
from app.services.vault.vault_paths import (
    vault_document_type_folder,
    vault_document_type_segment,
)


def _extracted_field(invoice: Invoice, key: str) -> str:
    fields = invoice.extracted_fields or {}
    value = fields.get(key)
    return str(value).strip() if value is not None else ""


def vault_type_folder_from_llm_or_heading(invoice: Invoice) -> str | None:
    """AI canonical type (preferred), else printed heading — Title Case only, no type allowlist."""
    from app.services.invoice.vision_header_extract import derive_canonical_document_type

    canonical = _extracted_field(invoice, CANONICAL_DOCUMENT_TYPE_KEY)
    heading = (invoice.document_heading or "").strip() or _extracted_field(
        invoice, "document_heading"
    )
    label = derive_canonical_document_type(
        document_heading=heading,
        canonical_document_type=canonical,
    )
    if label:
        return vault_document_type_folder(None, short_title=label)
    return None


def vault_document_type_folder_for_invoice(
    invoice: Invoice,
    document_types: list[DocumentTypeDefinition],
) -> str | None:
    """
    Resolve DT folder segment:

    1. Catalogue folder when document_type_code is set and book uses DT segments (Vault)
    2. Else LLM canonical_document_type
    3. Else raw document_heading
    4. Else Unclassified on Vault book; None on other books

    Vision path stores the type as the book itself (e.g. Packing List → vendor) — no nested
    type folder. Leftover catalogue codes on Unrouted must not block heading folders.
    Purchase/Sales with a catalogue code stay flat (legacy transactional books).
    """
    from app.services.vault.vault_paths import (
        ROUTE_UNROUTED,
        ROUTE_VAULT,
        is_standard_vault_book,
        vault_book_folder,
    )

    # Type-as-book (vision): book is already the type name — do not nest again.
    if not is_standard_vault_book(invoice.route_target):
        return None

    definition = resolve_definition_for_invoice(invoice, document_types)
    short_title = definition.short_title if definition else None
    title = definition.title if definition else None
    book = vault_book_folder(invoice.route_target)

    if (invoice.document_type_code or "").strip():
        catalogue = vault_document_type_segment(
            invoice.route_target,
            invoice.document_type_code,
            short_title=short_title,
            title=title,
        )
        if catalogue:
            return catalogue
        # Transactional books: keep flat when a DT code exists (legacy classify path).
        if book not in (ROUTE_UNROUTED, ROUTE_VAULT):
            return None

    heading_folder = vault_type_folder_from_llm_or_heading(invoice)
    if heading_folder:
        return heading_folder

    return vault_document_type_segment(
        invoice.route_target,
        None,
        short_title=None,
        title=None,
    )


def vault_document_type_titles_for_invoice(
    invoice: Invoice,
    document_types: list[DocumentTypeDefinition],
) -> tuple[str | None, str | None]:
    definition = resolve_definition_for_invoice(invoice, document_types)
    if definition is None:
        return None, None
    return definition.short_title, definition.title
