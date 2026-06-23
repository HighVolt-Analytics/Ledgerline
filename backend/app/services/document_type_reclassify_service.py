"""Re-apply document type classification from stored invoice fields."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.document_type_classifier import (
    apply_document_type_classification,
    classify_document_type,
)
from app.services.invoice_data import ParseConfidence, invoice_data_from_invoice
from app.services.invoice_evaluation_service import load_config_for_tenant

_SKIP_RECLASSIFY = frozenset(
    {
        InvoiceStatus.PENDING,
        InvoiceStatus.PARSING,
        InvoiceStatus.REJECTED,
        InvoiceStatus.DUPLICATE_SKIPPED,
    }
)


def _has_parse_snapshot(invoice: Invoice) -> bool:
    return bool(
        (invoice.vendor or "").strip()
        or (invoice.invoice_no or "").strip()
        or invoice.total is not None
        or (invoice.document_text or "").strip()
    )


async def reclassify_invoice_document_type(
    session: AsyncSession,
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload | None = None,
    parse_confidence: ParseConfidence | None = None,
) -> bool:
    """Re-run DT classification from persisted fields. Returns True if code/confidence changed."""
    if invoice.status in _SKIP_RECLASSIFY or not _has_parse_snapshot(invoice):
        return False

    if config is None:
        config = await load_config_for_tenant(session, invoice.tenant_id)

    parsed = invoice_data_from_invoice(invoice)
    before = (
        (invoice.document_type_code or "").strip().upper(),
        float(invoice.document_type_confidence or 0.0),
    )
    classification = classify_document_type(
        invoice=invoice,
        parsed=parsed,
        document_types=config.document_types,
        parse_confidence=parse_confidence,
        unclassified=config.document_classification,
    )
    apply_document_type_classification(invoice, classification)
    after = (
        (invoice.document_type_code or "").strip().upper(),
        float(invoice.document_type_confidence or 0.0),
    )
    if before != after:
        from app.services.invoice_evaluation_service import apply_invoice_evaluation

        await apply_invoice_evaluation(session, invoice, config=config, enqueue_pending=False)
        await session.flush()
        return True
    return False


async def reclassify_invoices_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: int,
    invoices: Sequence[Invoice],
    config: RuleBookConfigPayload | None = None,
) -> list[int]:
    changed: list[int] = []
    if config is None:
        tid = invoices[0].tenant_id if invoices else tenant_id
        config = await load_config_for_tenant(session, tid)
    for invoice in invoices:
        if await reclassify_invoice_document_type(session, invoice, config=config):
            changed.append(invoice.id)
    return changed
