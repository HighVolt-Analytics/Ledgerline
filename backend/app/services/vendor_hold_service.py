"""Hold invoices until unknown vendors are registered (architecture §7.4)."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.pending_vendor import PendingVendor
from app.services.audit_service import log_event
from app.services.invoice_evaluation_service import EVAL_PENDING_VENDOR
from app.services.invoice_reset import reset_invoice_for_reprocess
from app.services.master_data_service import list_pending_vendors


async def invoice_is_vendor_held(session: AsyncSession, invoice: Invoice) -> bool:
    if invoice.evaluation_status == EVAL_PENDING_VENDOR:
        return True

    name = (invoice.vendor or "").strip()
    if not name:
        pending_for_invoice = (
            await session.execute(
                select(PendingVendor.id).where(
                    PendingVendor.org_id == invoice.org_id,
                    PendingVendor.status == "pending",
                    PendingVendor.source_invoice_id == invoice.id,
                )
            )
        ).scalar_one_or_none()
        return pending_for_invoice is not None

    pending = await list_pending_vendors(session, invoice.org_id)
    key = name.lower()
    return any(row.detected_name.strip().lower() == key for row in pending)


async def apply_vendor_hold_if_needed(
    session: AsyncSession,
    invoice: Invoice,
) -> bool:
    """Set exception + pending_vendor when registration is required. Returns True if held."""
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
    org_id: int,
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
            Invoice.org_id == org_id,
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
    for inv in rows:
        await apply_invoice_evaluation(session, inv, enqueue_pending=False)
        if await invoice_is_vendor_held(session, inv):
            continue
        if inv.status == InvoiceStatus.EXCEPTION:
            await reset_invoice_for_reprocess(session, inv)
        await log_event(
            session,
            "vendor_registration_released",
            invoice_id=inv.id,
            detail={"vendor": inv.vendor},
        )
        released += 1
    return released
