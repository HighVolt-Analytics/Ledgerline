"""Hold invoices until unknown vendors are registered (architecture §7.4)."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.pending_vendor import PendingVendor
from app.services.audit_service import log_event
from app.services.bundle_vendor_service import (
    reconcile_dossier_vendor,
    vendors_align_to_same_master,
)
from app.services.expense_vendor_policy import is_unmatched_expense_vendor_status
from app.services.invoice_evaluation_service import EVAL_AUTO_CODED, EVAL_PENDING_VENDOR, ROUTE_PURCHASE, ROUTE_TEAM, ROUTE_VAULT
from app.services.invoice_reset import reset_invoice_for_reprocess
from app.services.master_data_service import list_pending_vendors


def _is_team_expense_route(invoice: Invoice) -> bool:
    return (invoice.route_target or "").strip() == ROUTE_TEAM


def _is_vault_route(invoice: Invoice) -> bool:
    return (invoice.route_target or "").strip() == ROUTE_VAULT


async def invoice_is_vendor_held(session: AsyncSession, invoice: Invoice) -> bool:
    if _is_team_expense_route(invoice):
        return False
    if is_unmatched_expense_vendor_status(invoice.evaluation_status):
        return False
    if await purchase_invoice_trusts_po_register(session, invoice):
        return False

    name = (invoice.vendor or "").strip()
    if name:
        from app.services.master_data_service import list_vendor_masters
        from app.services.vendor_detection import find_matching_vendor_master

        db_masters = await list_vendor_masters(session, invoice.tenant_id)
        if find_matching_vendor_master(name, invoice.abn, db_masters):
            return False

    if invoice.evaluation_status == EVAL_PENDING_VENDOR:
        return True
    if not name:
        pending_for_invoice = (
            await session.execute(
                select(PendingVendor.id).where(
                    PendingVendor.tenant_id == invoice.tenant_id,
                    PendingVendor.status == "pending",
                    PendingVendor.source_invoice_id == invoice.id,
                )
            )
        ).scalar_one_or_none()
        return pending_for_invoice is not None

    pending = await list_pending_vendors(session, invoice.tenant_id)
    key = name.lower()
    return any(row.detected_name.strip().lower() == key for row in pending)


def _is_purchase_supporting_document(invoice: Invoice) -> bool:
    return invoice.purchase_document_type in ("po", "grn")


async def purchase_invoice_trusts_po_register(
    session: AsyncSession,
    invoice: Invoice,
) -> bool:
    """Commercial purchase invoice linked to an existing PO register row."""
    if (invoice.route_target or "").strip() != ROUTE_PURCHASE:
        return False
    if _is_purchase_supporting_document(invoice):
        return False

    from app.services.purchase_match_service import load_purchase_order_for_invoice

    return await load_purchase_order_for_invoice(session, invoice) is not None


async def _release_hold_when_po_linked_purchase_invoice(
    session: AsyncSession,
    invoice: Invoice,
) -> bool:
    """PO-backed commercial invoice: PO approval is the vendor gate — skip registration hold."""
    if not await purchase_invoice_trusts_po_register(session, invoice):
        return False

    from app.services.purchase_match_service import load_purchase_order_for_invoice

    po = await load_purchase_order_for_invoice(session, invoice)
    if po:
        await reconcile_dossier_vendor(
            session,
            invoice,
            po,
            document_type=invoice.purchase_document_type,
        )

    if invoice.evaluation_status == EVAL_PENDING_VENDOR:
        invoice.evaluation_status = EVAL_AUTO_CODED
    await session.flush()
    return True


async def _release_hold_when_po_vendor_matches(
    session: AsyncSession,
    invoice: Invoice,
) -> bool:
    """Commercial invoice: trust PO register vendor over detection threshold."""
    from app.services.invoice_evaluation_service import EVAL_AUTO_CODED, EVAL_PENDING_VENDOR
    from app.services.purchase_match_service import load_purchase_order_for_invoice

    if invoice.evaluation_status != EVAL_PENDING_VENDOR:
        return False
    if _is_purchase_supporting_document(invoice):
        return False

    po = await load_purchase_order_for_invoice(session, invoice)
    if po is None or not (po.vendor or "").strip():
        return False

    inv_vendor = (invoice.vendor or "").strip()
    if not inv_vendor:
        invoice.vendor = po.vendor
        inv_vendor = po.vendor.strip()

    if not vendors_align_to_same_master(
        invoice.tenant_id,
        inv_vendor,
        invoice.abn,
        po.vendor,
        None,
        config=await load_config_for_tenant(session, invoice.tenant_id),
    ):
        return False

    invoice.vendor = (po.vendor or inv_vendor).strip()

    invoice.evaluation_status = EVAL_AUTO_CODED
    await session.flush()
    return True


async def apply_vendor_hold_if_needed(
    session: AsyncSession,
    invoice: Invoice,
) -> bool:
    """Set exception + pending_vendor when registration is required. Returns True if held."""
    if _is_purchase_supporting_document(invoice) or _is_team_expense_route(invoice) or _is_vault_route(invoice):
        return False

    if await _release_hold_when_po_linked_purchase_invoice(session, invoice):
        return False

    if await _release_hold_when_po_vendor_matches(session, invoice):
        return False

    if not await invoice_is_vendor_held(session, invoice):
        return False

    invoice.evaluation_status = EVAL_PENDING_VENDOR
    if invoice.status not in (
        InvoiceStatus.PROCESSED,
        InvoiceStatus.REJECTED,
        InvoiceStatus.DUPLICATE_SKIPPED,
    ):
        invoice.status = InvoiceStatus.EXCEPTION

    await log_event(
        session,
        "vendor_registration_hold",
        invoice_id=invoice.id,
        detail={
            "vendor": invoice.vendor,
            "vendor_confidence": invoice.vendor_confidence,
            "reason": "pending_vendor_registration",
        },
    )
    await session.flush()
    return True


async def release_invoices_after_vendor_promotion(
    session: AsyncSession,
    tenant_id: int,
    *,
    vendor_name: str,
    source_invoice_id: int | None = None,
) -> int:
    """Re-evaluate and release held invoices tied to a promoted vendor."""
    from app.services.invoice_evaluation_service import apply_invoice_evaluation

    name_key = vendor_name.strip().lower()
    stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.evaluation_status == EVAL_PENDING_VENDOR,
            Invoice.status.in_(
                (
                    InvoiceStatus.EXCEPTION,
                    InvoiceStatus.PENDING,
                    InvoiceStatus.PARSING,
                    InvoiceStatus.VALIDATING,
                    InvoiceStatus.MAPPING,
                )
            ),
        )
        .options(selectinload(Invoice.line_items))
    )
    if source_invoice_id is not None:
        stmt = stmt.where(
            or_(
                Invoice.id == source_invoice_id,
                Invoice.vendor.ilike(vendor_name.strip()),
            )
        )
    else:
        stmt = stmt.where(Invoice.vendor.ilike(vendor_name.strip()))

    rows = (await session.execute(stmt)).scalars().all()
    released = 0
    reprocess_ids: list[int] = []
    for inv in rows:
        await apply_invoice_evaluation(session, inv, enqueue_pending=False)
        if await invoice_is_vendor_held(session, inv):
            continue
        if inv.status == InvoiceStatus.EXCEPTION:
            await reset_invoice_for_reprocess(session, inv)
            if inv.raw_file_path:
                reprocess_ids.append(inv.id)
        await log_event(
            session,
            "vendor_registration_released",
            invoice_id=inv.id,
            detail={"vendor": vendor_name},
        )
        released += 1

    if reprocess_ids:
        from app.services.pipeline import process_invoice

        for invoice_id in reprocess_ids:
            loaded = (
                await session.execute(
                    select(Invoice)
                    .where(Invoice.id == invoice_id)
                    .options(selectinload(Invoice.line_items))
                )
            ).scalar_one()
            await process_invoice(session, loaded)

    return released
