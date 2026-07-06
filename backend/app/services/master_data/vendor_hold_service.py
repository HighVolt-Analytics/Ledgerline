"""Hold invoices until unknown vendors are registered (architecture §7.4)."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.pending_vendor import PendingVendor
from app.services.audit.audit_service import log_event
from app.services.master_data.bundle_vendor_service import (
    reconcile_dossier_vendor,
    vendors_align_to_same_master,
)
from app.services.purchase.expense_vendor_policy import is_unmatched_expense_vendor_status
from app.services.invoice.invoice_evaluation_service import (
    EVAL_AUTO_CODED,
    EVAL_PENDING_VENDOR,
    ROUTE_EXPENSES,
    ROUTE_PURCHASE,
    ROUTE_SALES,
)
from app.services.invoice.invoice_reset import reset_invoice_for_reprocess
from app.services.master_data.master_data_service import (
    classification_config_with_db_masters,
    list_pending_vendors,
)
from app.services.rule_book.rule_book_mapper import load_classification_config
from app.services.master_data.vendor_registration_policy import (
    resolve_document_type_definition,
    vendor_registration_required,
)


async def _registration_required_for_invoice(
    session: AsyncSession,
    invoice: Invoice,
) -> bool:
    config = await load_classification_config(session, invoice.tenant_id)
    definition = resolve_document_type_definition(
        invoice.document_type_code,
        document_types=config.document_types,
    )
    return vendor_registration_required(
        route_target=invoice.route_target,
        document_type=definition,
        purchase_document_type=invoice.purchase_document_type,
    )


async def invoice_is_vendor_held(session: AsyncSession, invoice: Invoice) -> bool:
    if is_unmatched_expense_vendor_status(invoice.evaluation_status):
        return False
    if not await _registration_required_for_invoice(session, invoice):
        return False
    if await purchase_invoice_trusts_po_register(session, invoice):
        return False

    name = (invoice.vendor or "").strip()
    if name:
        from app.services.master_data.master_data_service import list_vendor_masters
        from app.services.master_data.vendor_detection import find_matching_vendor_master

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
    """Commercial purchase invoice linked to a PO whose vendor is in the registered master."""
    if (invoice.route_target or "").strip() != ROUTE_PURCHASE:
        return False
    if _is_purchase_supporting_document(invoice):
        return False

    from app.services.purchase.purchase_match_service import load_purchase_order_for_invoice
    from app.services.master_data.vendor_detection import find_matching_vendor_master

    po = await load_purchase_order_for_invoice(session, invoice)
    if po is None:
        return False

    po_vendor = (po.vendor or "").strip()
    if not po_vendor:
        return False

    config = await load_classification_config(session, invoice.tenant_id)
    config = await classification_config_with_db_masters(session, invoice.tenant_id, config)
    if not find_matching_vendor_master(po_vendor, None, config.vendor_masters):
        return False

    inv_vendor = (invoice.vendor or "").strip()
    if inv_vendor and not vendors_align_to_same_master(
        invoice.tenant_id,
        inv_vendor,
        invoice.abn,
        po_vendor,
        None,
        config=config,
    ):
        return False

    return True


async def _release_hold_when_po_linked_purchase_invoice(
    session: AsyncSession,
    invoice: Invoice,
) -> bool:
    """PO-backed commercial invoice: PO approval is the vendor gate — skip registration hold."""
    if not await purchase_invoice_trusts_po_register(session, invoice):
        return False

    from app.services.purchase.purchase_match_service import load_purchase_order_for_invoice

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
    from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED, EVAL_PENDING_VENDOR
    from app.services.purchase.purchase_match_service import load_purchase_order_for_invoice

    if invoice.evaluation_status != EVAL_PENDING_VENDOR:
        return False
    if _is_purchase_supporting_document(invoice):
        return False

    po = await load_purchase_order_for_invoice(session, invoice)
    if po is None or not (po.vendor or "").strip():
        return False

    config = await load_classification_config(session, invoice.tenant_id)
    config = await classification_config_with_db_masters(session, invoice.tenant_id, config)
    from app.services.master_data.vendor_detection import find_matching_vendor_master

    po_vendor = (po.vendor or "").strip()
    if not find_matching_vendor_master(po_vendor, None, config.vendor_masters):
        return False

    inv_vendor = (invoice.vendor or "").strip()
    if not inv_vendor:
        invoice.vendor = po.vendor
        inv_vendor = po.vendor.strip()

    if not vendors_align_to_same_master(
        invoice.tenant_id,
        inv_vendor,
        invoice.abn,
        po_vendor,
        None,
        config=config,
    ):
        return False

    invoice.vendor = (po.vendor or inv_vendor).strip()

    invoice.evaluation_status = EVAL_AUTO_CODED
    await session.flush()
    return True


_VENDOR_OUTCOME_EVENTS = frozenset(
    {
        "vendor_registration_hold",
        "vendor_registration_cleared",
        "vendor_registration_waived",
    }
)


async def _log_vendor_outcome_if_changed(
    session: AsyncSession,
    invoice: Invoice,
    event: str,
    *,
    detail: dict[str, object],
) -> None:
    """Record vendor-hold evaluation once per outcome (avoids triple-logging in pipeline)."""
    from app.models.audit import AuditLog

    latest = (
        await session.execute(
            select(AuditLog.event, AuditLog.detail)
            .where(
                AuditLog.invoice_id == invoice.id,
                AuditLog.event.in_(_VENDOR_OUTCOME_EVENTS),
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
    ).first()
    if latest is not None:
        last_event, last_detail = latest
        last_reason = ""
        if isinstance(last_detail, dict):
            last_reason = str(last_detail.get("reason") or "").strip()
        new_reason = str(detail.get("reason") or "").strip()
        if last_event == event and last_reason == new_reason:
            return

    await log_event(session, event, invoice_id=invoice.id, detail=detail)


async def _unknown_vendor_needs_registration(
    session: AsyncSession,
    invoice: Invoice,
) -> bool:
    """True when vendor is not in masters and registration is required for this document."""
    if not await _registration_required_for_invoice(session, invoice):
        return False
    if _is_purchase_supporting_document(invoice):
        return False
    if await purchase_invoice_trusts_po_register(session, invoice):
        return False

    name = (invoice.vendor or "").strip()
    if not name:
        return False

    from app.services.master_data.master_data_service import list_vendor_masters
    from app.services.master_data.vendor_detection import find_matching_vendor_master

    db_masters = await list_vendor_masters(session, invoice.tenant_id)
    if find_matching_vendor_master(name, invoice.abn, db_masters):
        return False

    route = (invoice.route_target or "").strip()
    if route == ROUTE_EXPENSES:
        config = await load_classification_config(session, invoice.tenant_id)
        threshold = float(config.vendor_detection_config.threshold)
        confidence = float(invoice.vendor_confidence or 0)
        if confidence >= threshold:
            return False
        from app.services.purchase.expense_vendor_policy import expense_vendor_hold_above

        amount = float(invoice.total) if invoice.total is not None else None
        if amount is None:
            return True
        return amount > expense_vendor_hold_above(config)

    # Purchase and other payable routes: no master match always requires registration.
    return True


async def apply_vendor_hold_if_needed(
    session: AsyncSession,
    invoice: Invoice,
) -> bool:
    """Set exception + pending_vendor when registration is required. Returns True if held."""
    if (invoice.route_target or "").strip() == ROUTE_SALES:
        from app.services.master_data.customer_hold_service import apply_customer_hold_if_needed

        return await apply_customer_hold_if_needed(session, invoice)

    if not await _registration_required_for_invoice(session, invoice):
        await _log_vendor_outcome_if_changed(
            session,
            invoice,
            "vendor_registration_waived",
            detail={"reason": "registration_not_required"},
        )
        return False

    if _is_purchase_supporting_document(invoice):
        await _log_vendor_outcome_if_changed(
            session,
            invoice,
            "vendor_registration_waived",
            detail={
                "reason": "supporting_purchase_document",
                "purchase_document_type": invoice.purchase_document_type,
            },
        )
        return False

    if await _release_hold_when_po_linked_purchase_invoice(session, invoice):
        await _log_vendor_outcome_if_changed(
            session,
            invoice,
            "vendor_registration_waived",
            detail={
                "reason": "po_register_trusted",
                "vendor": invoice.vendor,
                "po_reference": invoice.po_reference,
            },
        )
        return False

    if await _release_hold_when_po_vendor_matches(session, invoice):
        await _log_vendor_outcome_if_changed(
            session,
            invoice,
            "vendor_registration_cleared",
            detail={
                "reason": "po_vendor_aligned",
                "vendor": invoice.vendor,
            },
        )
        return False

    if not await invoice_is_vendor_held(session, invoice):
        if not await _unknown_vendor_needs_registration(session, invoice):
            from app.services.master_data.master_data_service import list_vendor_masters
            from app.services.master_data.vendor_detection import find_matching_vendor_master

            name = (invoice.vendor or "").strip()
            db_masters = await list_vendor_masters(session, invoice.tenant_id)
            known = find_matching_vendor_master(name, invoice.abn, db_masters) if name else None
            reason = "vendor_in_master" if known else "confidence_above_threshold"
            await _log_vendor_outcome_if_changed(
                session,
                invoice,
                "vendor_registration_cleared",
                detail={
                    "reason": reason,
                    "vendor": invoice.vendor,
                    "vendor_confidence": invoice.vendor_confidence,
                },
            )
            return False

    invoice.evaluation_status = EVAL_PENDING_VENDOR
    if invoice.vendor_confidence is None:
        invoice.vendor_confidence = 0.0
    if invoice.status not in (
        InvoiceStatus.REJECTED,
        InvoiceStatus.DUPLICATE_SKIPPED,
    ):
        invoice.status = InvoiceStatus.EXCEPTION

    await _log_vendor_outcome_if_changed(
        session,
        invoice,
        "vendor_registration_hold",
        detail={
            "vendor": invoice.vendor,
            "vendor_confidence": invoice.vendor_confidence,
            "reason": "pending_vendor_registration",
        },
    )
    from app.services.invoice.invoice_evaluation_service import ensure_pending_vendor_queued

    await ensure_pending_vendor_queued(session, invoice)
    await session.flush()
    from app.services.shared.notifier import send_notification

    send_notification(invoice, InvoiceStatus.EXCEPTION)
    return True


async def release_invoices_after_vendor_promotion(
    session: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    *,
    vendor_name: str,
    source_invoice_id: int | None = None,
) -> int:
    """Re-evaluate and release held invoices tied to a promoted vendor."""
    from app.services.invoice.invoice_evaluation_service import apply_invoice_evaluation
    from app.tenant_scoped import coerce_tenant_uuid

    tid = coerce_tenant_uuid(tenant_id)
    if tid is None:
        return 0

    name_key = vendor_name.strip().lower()
    stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tid,
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
        from app.services.invoice.pipeline import process_invoice

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
