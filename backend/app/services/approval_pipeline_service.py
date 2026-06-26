"""Human approval overrides when re-running the invoice pipeline."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.services.document_type_approval_service import has_document_approval
from app.services.invoice_evaluation_service import EVAL_AUTO_CODED


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
    """Prefer payable AP processing after explicit human approval."""
    from app.services.purchase_document_service import (
        PurchaseDocumentType,
        normalize_purchase_document_type,
    )

    invoice.evaluation_status = EVAL_AUTO_CODED
    doc_type = normalize_purchase_document_type(invoice.purchase_document_type)
    if doc_type in (PurchaseDocumentType.PO.value, PurchaseDocumentType.GRN.value):
        invoice.purchase_document_type = PurchaseDocumentType.INVOICE.value
