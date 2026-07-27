"""Accrual (invoice) date policy for posting and reconciliation."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.audit.audit_service import log_event
from app.services.invoice.invoice_evaluation_service import EVAL_NEEDS_REVIEW
from app.services.shared.notifier import send_notification


def invoice_accrual_date(invoice: Invoice) -> date | None:
    """Economic accrual date — required before GL posting."""
    return invoice.invoice_date


def effective_invoice_recon_date(invoice: Invoice) -> date | None:
    """Reconciliation bucket date; must match journal entry date."""
    return invoice.invoice_date


async def halt_if_missing_accrual_date(
    session: AsyncSession,
    invoice: Invoice,
    *,
    resume: str = "fields_review",
) -> bool:
    """Stop before journaling when invoice date is unknown.

    Returns True when processing was halted.
    """
    if invoice_accrual_date(invoice) is not None:
        return False

    invoice.status = InvoiceStatus.EXCEPTION
    if not (invoice.evaluation_status or "").strip():
        invoice.evaluation_status = EVAL_NEEDS_REVIEW
    await log_event(
        session,
        "accrual_date_required",
        invoice_id=invoice.id,
        detail={
            "reason": "Invoice date is required before accrual posting and reconciliation",
            "resume": resume,
        },
    )
    send_notification(invoice, InvoiceStatus.EXCEPTION)
    return True
