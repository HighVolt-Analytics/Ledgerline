"""Hold sales invoices until unknown customers are registered."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.pending_customer import PendingCustomer
from app.services.audit.audit_service import log_event
from app.services.invoice.invoice_evaluation_service import (
    EVAL_AUTO_CODED,
    EVAL_PENDING_VENDOR,
    ROUTE_SALES,
)
from app.services.invoice.invoice_reset import reset_invoice_for_reprocess
from app.services.master_data.customer_master_service import list_pending_customers
from app.services.master_data.vendor_registration_policy import (
    customer_registration_required,
    resolve_document_type_definition,
)
from app.services.rule_book.rule_book_mapper import load_classification_config


async def _registration_required_for_invoice(
    session: AsyncSession,
    invoice: Invoice,
) -> bool:
    config = await load_classification_config(session, invoice.tenant_id)
    definition = resolve_document_type_definition(
        invoice.document_type_code,
        document_types=config.document_types,
    )
    return customer_registration_required(
        route_target=invoice.route_target,
        document_type=definition,
    )


async def invoice_is_customer_held(session: AsyncSession, invoice: Invoice) -> bool:
    if not await _registration_required_for_invoice(session, invoice):
        return False

    name = (invoice.vendor or "").strip()
    if name:
        from app.services.master_data.customer_master_service import list_customer_masters
        from app.services.master_data.vendor_detection import find_matching_customer_master

        db_masters = await list_customer_masters(session, invoice.tenant_id)
        if find_matching_customer_master(name, invoice.abn, db_masters):
            return False

    if invoice.evaluation_status == EVAL_PENDING_VENDOR:
        return True
    if not name:
        pending_for_invoice = (
            await session.execute(
                select(PendingCustomer.id).where(
                    PendingCustomer.tenant_id == invoice.tenant_id,
                    PendingCustomer.status == "pending",
                    PendingCustomer.source_invoice_id == invoice.id,
                )
            )
        ).scalar_one_or_none()
        return pending_for_invoice is not None

    pending = await list_pending_customers(session, invoice.tenant_id)
    key = name.lower()
    return any(row.detected_name.strip().lower() == key for row in pending)


async def _unknown_customer_needs_registration(
    session: AsyncSession,
    invoice: Invoice,
) -> bool:
    if not await _registration_required_for_invoice(session, invoice):
        return False

    name = (invoice.vendor or "").strip()
    if not name:
        return False

    from app.services.master_data.customer_master_service import list_customer_masters
    from app.services.master_data.vendor_detection import find_matching_customer_master

    db_masters = await list_customer_masters(session, invoice.tenant_id)
    if find_matching_customer_master(name, invoice.abn, db_masters):
        return False

    config = await load_classification_config(session, invoice.tenant_id)
    threshold = float(config.vendor_detection_config.threshold)
    confidence = float(invoice.vendor_confidence or 0)
    return confidence < threshold


async def _log_customer_outcome_if_changed(
    session: AsyncSession,
    invoice: Invoice,
    event: str,
    *,
    detail: dict,
) -> None:
    from app.models.audit import AuditLog

    last = (
        await session.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id == invoice.id,
                AuditLog.event.in_(
                    [
                        "customer_registration_hold",
                        "customer_registration_cleared",
                        "customer_registration_waived",
                    ]
                ),
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last is not None:
        last_event = last.event
        last_detail = last.detail if isinstance(last.detail, dict) else {}
        last_reason = str(last_detail.get("reason") or "").strip()
        new_reason = str(detail.get("reason") or "").strip()
        if last_event == event and last_reason == new_reason:
            return

    await log_event(session, event, invoice_id=invoice.id, detail=detail)


async def apply_customer_hold_if_needed(
    session: AsyncSession,
    invoice: Invoice,
) -> bool:
    """Set exception + pending_vendor when customer registration is required."""
    if (invoice.route_target or "").strip() != ROUTE_SALES:
        return False

    if not await _registration_required_for_invoice(session, invoice):
        await _log_customer_outcome_if_changed(
            session,
            invoice,
            "customer_registration_waived",
            detail={"reason": "registration_not_required"},
        )
        return False

    if not await invoice_is_customer_held(session, invoice):
        if not await _unknown_customer_needs_registration(session, invoice):
            from app.services.master_data.customer_master_service import list_customer_masters
            from app.services.master_data.vendor_detection import find_matching_customer_master

            name = (invoice.vendor or "").strip()
            db_masters = await list_customer_masters(session, invoice.tenant_id)
            known = find_matching_customer_master(name, invoice.abn, db_masters) if name else None
            reason = "customer_in_master" if known else "confidence_above_threshold"
            await _log_customer_outcome_if_changed(
                session,
                invoice,
                "customer_registration_cleared",
                detail={
                    "reason": reason,
                    "customer": invoice.vendor,
                    "customer_confidence": invoice.vendor_confidence,
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

    await _log_customer_outcome_if_changed(
        session,
        invoice,
        "customer_registration_hold",
        detail={
            "customer": invoice.vendor,
            "customer_confidence": invoice.vendor_confidence,
            "reason": "pending_customer_registration",
        },
    )
    from app.services.invoice.invoice_evaluation_service import ensure_pending_customer_queued

    await ensure_pending_customer_queued(session, invoice)
    await session.flush()
    from app.services.shared.notifier import send_notification

    send_notification(invoice, InvoiceStatus.EXCEPTION)
    return True


async def release_invoices_after_customer_promotion(
    session: AsyncSession,
    tenant_id: uuid.UUID | int | str,
    *,
    customer_name: str,
    source_invoice_id: int | None = None,
) -> int:
    from app.services.invoice.invoice_evaluation_service import apply_invoice_evaluation
    from app.tenant_scoped import coerce_tenant_uuid

    tid = coerce_tenant_uuid(tenant_id)
    if tid is None:
        return 0

    name_key = customer_name.strip().lower()
    stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tid,
            Invoice.evaluation_status == EVAL_PENDING_VENDOR,
            Invoice.route_target == ROUTE_SALES,
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
                Invoice.vendor.ilike(customer_name.strip()),
            )
        )
    else:
        stmt = stmt.where(Invoice.vendor.ilike(customer_name.strip()))

    rows = (await session.execute(stmt)).scalars().all()
    released = 0
    reprocess_ids: list[int] = []
    for inv in rows:
        if inv.vendor and inv.vendor.strip().lower() != name_key:
            continue
        inv.evaluation_status = EVAL_AUTO_CODED
        if inv.status == InvoiceStatus.EXCEPTION:
            inv.status = InvoiceStatus.PENDING
        await apply_invoice_evaluation(session, inv, enqueue_pending=False)
        if inv.status in (InvoiceStatus.PENDING, InvoiceStatus.PARSING):
            reprocess_ids.append(inv.id)
        released += 1

    for invoice_id in reprocess_ids:
        inv = await session.get(Invoice, invoice_id)
        if inv is not None:
            await reset_invoice_for_reprocess(session, inv)

    await session.flush()
    return released
