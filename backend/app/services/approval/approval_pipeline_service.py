"""Human approval overrides when re-running the invoice pipeline."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.services.classification.document_type_approval_service import has_document_approval


def payable_fields_complete(invoice: Invoice) -> bool:
    if not (invoice.vendor or "").strip():
        return False
    if invoice.due_date is None:
        return False
    if invoice.total is None or invoice.total <= Decimal("0"):
        return False
    return True


async def human_approved_payable_bypass(session: AsyncSession, invoice: Invoice) -> bool:
    """True when a user approved from the queue and core payable fields are present."""
    if not await has_document_approval(session, invoice.id):
        return False
    return payable_fields_complete(invoice)


def apply_human_approval_processing_defaults(invoice: Invoice) -> None:
    """Normalize purchase role after explicit human approval; do not clear vendor flags."""
    from app.services.purchase.purchase_document_service import (
        PurchaseDocumentType,
        normalize_purchase_document_type,
    )

    doc_type = normalize_purchase_document_type(invoice.purchase_document_type)
    if doc_type in (PurchaseDocumentType.PO.value, PurchaseDocumentType.GRN.value):
        invoice.purchase_document_type = PurchaseDocumentType.INVOICE.value


def human_approval_may_bypass_validation(results: list) -> bool:
    """Human approve may skip non-vendor validation failures; VR12 always blocks."""
    from app.services.rule_book.validator import ValidationResult

    for row in results:
        if not isinstance(row, ValidationResult):
            continue
        if row.rule == "VR12" and not row.passed and not row.skipped:
            return False
    return True
