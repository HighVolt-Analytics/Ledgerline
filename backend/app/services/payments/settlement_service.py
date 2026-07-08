"""Post-process settlement (payment / collection) with audit when skipped."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.audit.audit_service import log_event
from app.services.integration.collection_service import ensure_receivable_for_invoice
from app.services.payments.payment_service import ensure_payment_for_invoice
from app.services.purchase.purchase_document_service import is_commercial_purchase_invoice
from app.services.sales.sales_document_service import is_commercial_sales_invoice


def payment_skip_reason(invoice: Invoice) -> str | None:
    if not is_commercial_purchase_invoice(invoice):
        return None
    if invoice.status != InvoiceStatus.PROCESSED:
        return "not_processed"
    if not (invoice.vendor or "").strip():
        return "missing_vendor"
    if invoice.total is None or invoice.total <= 0:
        return "missing_or_invalid_total"
    if invoice.due_date is None:
        return "missing_due_date"
    return None


def collection_skip_reason(invoice: Invoice) -> str | None:
    if not is_commercial_sales_invoice(invoice):
        return None
    from app.services.invoice.invoice_evaluation_service import ROUTE_SALES

    if (invoice.route_target or "").strip() != ROUTE_SALES:
        return None
    if invoice.status != InvoiceStatus.PROCESSED:
        return "not_processed"
    if not (invoice.vendor or "").strip():
        return "missing_customer"
    if invoice.total is None or invoice.total <= 0:
        return "missing_or_invalid_total"
    if invoice.due_date is None:
        return "missing_due_date"
    return None


async def ensure_payment_with_audit(
    session: AsyncSession,
    invoice: Invoice,
):
    reason = payment_skip_reason(invoice)
    payment = await ensure_payment_for_invoice(session, invoice)
    if payment is None and reason is not None:
        await log_event(
            session,
            "settlement_skipped",
            invoice_id=invoice.id,
            detail={
                "kind": "payment",
                "reason": reason,
                "route_target": invoice.route_target,
            },
        )
    return payment


async def ensure_receivable_with_audit(
    session: AsyncSession,
    invoice: Invoice,
):
    reason = collection_skip_reason(invoice)
    collection = await ensure_receivable_for_invoice(session, invoice)
    if collection is None and reason is not None:
        await log_event(
            session,
            "settlement_skipped",
            invoice_id=invoice.id,
            detail={
                "kind": "collection",
                "reason": reason,
                "route_target": invoice.route_target,
            },
        )
    return collection
