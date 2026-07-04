"""Finish pipeline for supporting / non-posting documents (no GL journal)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.document_type import DocumentTypeDefinition
from app.services.audit.audit_service import log_event
from app.services.classification.document_type_playbook_profile_service import clear_invoice_gl_mapping
from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED
from app.services.shared.notifier import send_notification


def _mark_invoice_processed(invoice: Invoice) -> None:
    invoice.status = InvoiceStatus.PROCESSED


async def finish_non_posting_document(
    session: AsyncSession,
    invoice: Invoice,
    *,
    definition: DocumentTypeDefinition | None = None,
    audit_event: str = "supporting_document_processed",
    detail: dict | None = None,
) -> None:
    """Complete documents that are stored for match/audit only — never GL-mapped."""
    clear_invoice_gl_mapping(invoice)
    invoice.evaluation_status = EVAL_AUTO_CODED
    _mark_invoice_processed(invoice)
    await session.flush()
    payload: dict = {"route_target": invoice.route_target}
    if definition is not None:
        payload["document_type_code"] = definition.code
        payload["playbook_profile"] = definition.playbook_profile
    if detail:
        payload.update(detail)
    await log_event(
        session,
        audit_event,
        invoice_id=invoice.id,
        detail=payload,
    )
    send_notification(invoice, InvoiceStatus.PROCESSED)
