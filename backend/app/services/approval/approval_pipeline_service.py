"""Human approval overrides when re-running the invoice pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.services.classification.document_type_approval_service import has_document_approval

if TYPE_CHECKING:
    from app.schemas.document_type import DocumentTypeDefinition


def payable_fields_complete(
    invoice: Invoice,
    definition: DocumentTypeDefinition | None = None,
) -> bool:
    """True when the document type's required header fields are present.

    Does not invent vendor/total. Completeness is the DT required-fields list.
    """
    from app.services.invoice.vision_posting_continue import header_fields_complete

    return header_fields_complete(invoice, definition)


async def document_type_definition_for_invoice(session: AsyncSession, invoice: Invoice):
    from app.services.classification.document_type_catalog import get_document_type_definition
    from app.services.invoice.invoice_evaluation_service import load_config_for_tenant

    config = await load_config_for_tenant(session, invoice.tenant_id)
    return get_document_type_definition(
        invoice.document_type_code,
        document_types=config.document_types,
    )


async def human_approved_payable_bypass(session: AsyncSession, invoice: Invoice) -> bool:
    """True when a user approved from the queue and DT-required fields are present."""
    if not await has_document_approval(session, invoice.id):
        return False
    definition = await document_type_definition_for_invoice(session, invoice)
    return payable_fields_complete(invoice, definition)


def apply_human_approval_processing_defaults(invoice: Invoice) -> None:
    """Normalize purchase role after explicit human approval; do not clear vendor flags."""
    from app.services.purchase.purchase_document_service import (
        PurchaseDocumentType,
        normalize_purchase_document_type,
    )

    doc_type = normalize_purchase_document_type(invoice.purchase_document_type)
    if doc_type in (PurchaseDocumentType.PO.value, PurchaseDocumentType.GRN.value):
        invoice.purchase_document_type = PurchaseDocumentType.INVOICE.value


_NON_BYPASSABLE_RULES = frozenset({"VR12", "VR13"})


def human_approval_may_bypass_validation(results: list) -> bool:
    """Human approve may skip most validation failures; vendor-identity and
    bank-details fraud checks (VR12, VR13) always block."""
    from app.services.rule_book.validator import ValidationResult

    for row in results:
        if not isinstance(row, ValidationResult):
            continue
        if row.rule in _NON_BYPASSABLE_RULES and not row.passed and not row.skipped:
            return False
    return True
