"""Re-process held commercial invoices when sibling dossier documents arrive."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus, PurchaseDocumentType, SalesDocumentType
from app.services.audit.audit_service import log_event
from app.services.invoice.invoice_evaluation_service import (
    EVAL_PENDING_APPROVAL,
    ROUTE_PURCHASE,
    ROUTE_SALES,
)
from app.services.invoice.invoice_reset import requeue_invoice_for_pipeline, should_preserve_extracted_on_requeue
from app.services.purchase.po_reference import is_plausible_po_reference
from app.services.sales.so_reference import is_plausible_so_reference

_REPROCESSABLE_STATUSES = {
    InvoiceStatus.EXCEPTION,
    InvoiceStatus.VALIDATING,
    InvoiceStatus.MAPPING,
}

_HOLD_EVAL_STATUSES = frozenset({"awaiting_po", "awaiting_so"})

# Commercial invoices waiting for human approval do not benefit from PO/SO re-sync.
_SKIP_REPROCESS_EVAL_FOR_REFERENCE_TRIGGER = frozenset({EVAL_PENDING_APPROVAL})

# Vision-understood hold: soft-bundled only — never re-queue into the full pipeline.
_NEVER_SIBLING_REPROCESS_EVAL = frozenset({"awaiting_classification"})

_PENDING_PIPELINE_STATUSES = frozenset(
    {
        InvoiceStatus.PENDING,
        InvoiceStatus.PARSING,
        InvoiceStatus.VALIDATING,
        InvoiceStatus.MAPPING,
        InvoiceStatus.JOURNALING,
        InvoiceStatus.RECONCILING,
    }
)

_scheduled_sibling_reprocess: dict[uuid.UUID, set[int]] = defaultdict(set)


def _normalize_anchor(value: str | None) -> str:
    return (value or "").strip().upper()


async def _skip_sibling_reprocess(
    session: AsyncSession,
    commercial: Invoice,
    triggering_invoice_id: int | None,
    *,
    route_target: str,
) -> bool:
    """Skip redundant full-pipeline runs when only a reference doc re-synced."""
    eval_status = (commercial.evaluation_status or "").strip().lower()
    if eval_status not in _SKIP_REPROCESS_EVAL_FOR_REFERENCE_TRIGGER:
        return False
    if triggering_invoice_id is None:
        return True

    trigger = await session.get(Invoice, triggering_invoice_id)
    if trigger is None:
        return True

    route = (route_target or "").strip()
    if route == ROUTE_PURCHASE:
        trigger_doc = (trigger.purchase_document_type or "").strip().lower()
        return trigger_doc in {PurchaseDocumentType.PO.value, ""}
    if route == ROUTE_SALES:
        trigger_doc = (trigger.sales_document_type or "").strip().lower()
        return trigger_doc in {SalesDocumentType.SO.value, ""}
    return False


def schedule_sibling_reprocess(
    invoice_ids: list[int],
    *,
    tenant_id: uuid.UUID,
) -> None:
    """Queue sibling pipelines only after the triggering run commits its DB session."""
    if not invoice_ids:
        return
    _scheduled_sibling_reprocess[tenant_id].update(invoice_ids)


async def flush_scheduled_sibling_reprocess() -> None:
    """Start deferred sibling reprocess tasks once the caller's session has committed."""
    if not _scheduled_sibling_reprocess:
        return
    pending = {
        tenant_id: list(dict.fromkeys(invoice_ids))
        for tenant_id, invoice_ids in _scheduled_sibling_reprocess.items()
        if invoice_ids
    }
    _scheduled_sibling_reprocess.clear()
    if not pending:
        return
    from app.workers.tasks import queue_invoices_for_processing

    for tenant_id, invoice_ids in pending.items():
        await queue_invoices_for_processing(invoice_ids, tenant_id=tenant_id)


async def _commercial_invoices_on_sales_anchor(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    so_reference: str,
    exclude_invoice_id: int | None,
) -> list[Invoice]:
    token = _normalize_anchor(so_reference)
    if not token or not is_plausible_so_reference(so_reference):
        return []

    stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            func.upper(func.coalesce(Invoice.so_reference, "")) == token,
            Invoice.route_target == ROUTE_SALES,
        )
        .options(selectinload(Invoice.line_items))
    )
    if exclude_invoice_id is not None:
        stmt = stmt.where(Invoice.id != exclude_invoice_id)

    rows = (await session.execute(stmt)).scalars().all()
    return [
        row
        for row in rows
        if (row.sales_document_type or "").strip().lower()
        not in {SalesDocumentType.SO.value, SalesDocumentType.DN.value}
        and (
            row.status in _REPROCESSABLE_STATUSES
            or (row.evaluation_status or "").strip().lower() in _HOLD_EVAL_STATUSES
        )
    ]


async def _commercial_invoices_on_purchase_anchor(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    po_reference: str,
    exclude_invoice_id: int | None,
) -> list[Invoice]:
    token = _normalize_anchor(po_reference)
    if not token or not is_plausible_po_reference(po_reference):
        return []

    stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            func.upper(func.coalesce(Invoice.po_reference, "")) == token,
            Invoice.route_target == ROUTE_PURCHASE,
        )
        .options(selectinload(Invoice.line_items))
    )
    if exclude_invoice_id is not None:
        stmt = stmt.where(Invoice.id != exclude_invoice_id)

    rows = (await session.execute(stmt)).scalars().all()
    return [
        row
        for row in rows
        if (row.purchase_document_type or "").strip().lower()
        not in {PurchaseDocumentType.PO.value, PurchaseDocumentType.GRN.value}
        and (
            row.status in _REPROCESSABLE_STATUSES
            or (row.evaluation_status or "").strip().lower() in _HOLD_EVAL_STATUSES
        )
    ]


async def reprocess_held_commercial_invoices_on_anchor(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    route_target: str,
    anchor_ref: str,
    triggering_invoice_id: int | None = None,
) -> list[int]:
    """Re-queue commercial invoices held on the same dossier anchor after a sibling upload."""
    route = (route_target or "").strip()
    anchor = (anchor_ref or "").strip()
    if not anchor:
        return []

    if route == ROUTE_SALES:
        candidates = await _commercial_invoices_on_sales_anchor(
            session,
            tenant_id=tenant_id,
            so_reference=anchor,
            exclude_invoice_id=triggering_invoice_id,
        )
    elif route == ROUTE_PURCHASE:
        candidates = await _commercial_invoices_on_purchase_anchor(
            session,
            tenant_id=tenant_id,
            po_reference=anchor,
            exclude_invoice_id=triggering_invoice_id,
        )
    else:
        return []

    if not candidates:
        return []

    reprocessed: list[int] = []
    for inv in candidates:
        if not inv.raw_file_path:
            continue
        if inv.status in _PENDING_PIPELINE_STATUSES:
            continue
        eval_status = (inv.evaluation_status or "").strip().lower()
        if eval_status in _NEVER_SIBLING_REPROCESS_EVAL:
            continue
        if await _skip_sibling_reprocess(
            session,
            inv,
            triggering_invoice_id,
            route_target=route,
        ):
            continue
        preserve = await should_preserve_extracted_on_requeue(session, inv)
        await requeue_invoice_for_pipeline(
            session,
            inv,
            preserve_document_type=True,
            preserve_extracted_fields=preserve,
        )
        await log_event(
            session,
            "dossier_sibling_reprocess_queued",
            invoice_id=inv.id,
            detail={
                "anchor_ref": anchor,
                "route_target": route,
                "triggering_invoice_id": triggering_invoice_id,
            },
        )
        reprocessed.append(inv.id)

    await session.flush()
    if reprocessed:
        schedule_sibling_reprocess(reprocessed, tenant_id=tenant_id)

    return reprocessed
