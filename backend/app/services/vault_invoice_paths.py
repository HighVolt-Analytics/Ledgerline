"""Resolve vault folder segments from invoice + document-type catalogue."""

from __future__ import annotations

from app.models.invoice import Invoice
from app.schemas.document_type import DocumentTypeDefinition
from app.services.document_type_playbook_service import resolve_definition_for_invoice
from app.services.vault_paths import vault_document_type_segment


def vault_document_type_folder_for_invoice(
    invoice: Invoice,
    document_types: list[DocumentTypeDefinition],
) -> str | None:
    definition = resolve_definition_for_invoice(invoice, document_types)
    return vault_document_type_segment(
        invoice.route_target,
        invoice.document_type_code,
        short_title=definition.short_title if definition else None,
        title=definition.title if definition else None,
    )


def vault_document_type_titles_for_invoice(
    invoice: Invoice,
    document_types: list[DocumentTypeDefinition],
) -> tuple[str | None, str | None]:
    definition = resolve_definition_for_invoice(invoice, document_types)
    if definition is None:
        return None, None
    return definition.short_title, definition.title
