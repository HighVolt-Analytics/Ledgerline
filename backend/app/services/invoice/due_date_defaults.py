"""Due-date defaults for commercial / posting documents.

When a document has an invoice date but no printed due date (export LUT,
due-on-receipt, COD), use invoice_date so vision header gates and payment
scheduling are not blocked by a missing optional print field.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.invoice import Invoice
    from app.schemas.document_type import DocumentTypeDefinition
    from app.services.invoice.invoice_data import InvoiceData


def should_default_due_on_receipt(
    definition: DocumentTypeDefinition | None,
) -> bool:
    """True only when the DT playbook marks due_date as compulsory."""
    if definition is None:
        return False
    from app.services.classification.document_type_playbook_profile_service import (
        allows_posting_pipeline,
    )
    from app.services.classification.document_type_playbook_service import (
        effective_required_fields,
    )

    if not allows_posting_pipeline(definition):
        return False
    required = {str(k).strip().lower() for k in effective_required_fields(definition)}
    return "due_date" in required


def resolve_due_on_receipt_date(
    *,
    due_date: date | None,
    invoice_date: date | None,
    definition: DocumentTypeDefinition | None = None,
) -> date | None:
    if due_date is not None:
        return due_date
    if invoice_date is None:
        return None
    if not should_default_due_on_receipt(definition):
        return None
    return invoice_date


def apply_due_on_receipt_to_invoice(
    invoice: Invoice,
    definition: DocumentTypeDefinition | None = None,
) -> bool:
    """Persist due_date = invoice_date when due date is blank. Returns True if set."""
    resolved = resolve_due_on_receipt_date(
        due_date=getattr(invoice, "due_date", None),
        invoice_date=getattr(invoice, "invoice_date", None),
        definition=definition,
    )
    if resolved is None or invoice.due_date == resolved:
        return False
    if invoice.due_date is not None:
        return False
    invoice.due_date = resolved
    return True


def apply_due_on_receipt_to_parsed(
    parsed: InvoiceData,
    definition: DocumentTypeDefinition | None = None,
) -> bool:
    """Fill parsed.due_date from invoice_date when blank. Returns True if set."""
    resolved = resolve_due_on_receipt_date(
        due_date=parsed.due_date,
        invoice_date=parsed.invoice_date,
        definition=definition,
    )
    if resolved is None or parsed.due_date is not None:
        return False
    parsed.due_date = resolved
    return True
