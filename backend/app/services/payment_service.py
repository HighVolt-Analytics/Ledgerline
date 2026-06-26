"""Payment disbursement workflow (Phase F)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.schemas.payment import (
    PaymentResponse,
    PaymentStatusUpdate,
    WalletSummaryResponse,
    WalletTransactionResponse,
)

_OPEN_STATUSES = (
    PaymentStatus.QUEUE,
    PaymentStatus.AWAITING,
    PaymentStatus.SCHEDULED,
)


def _payment_tier_approvers(amount: Decimal) -> list[dict[str, str]]:
    value = float(amount)
    if value >= 60_000:
        return [
            {"id": "cfo", "name": "CFO", "role": "CFO", "state": "pending"},
            {"id": "ceo", "name": "CEO", "role": "CEO", "state": "pending"},
        ]
    if value >= 25_000:
        return [{"id": "cfo", "name": "CFO", "role": "CFO", "state": "pending"}]
    if value >= 5_000:
        return [{"id": "fin-lead", "name": "Finance Lead", "role": "Finance Lead", "state": "pending"}]
    if value >= 500:
        return [{"id": "mgr", "name": "Manager", "role": "Manager", "state": "pending"}]
    return []


def payment_to_response(
    row: Payment,
    *,
    vendor_payout_status: str | None = None,
    vendor_payout_method_type: str | None = None,
    execution_readiness_status: str | None = None,
    execution_blocking_reason: str | None = None,
) -> PaymentResponse:
    tab = row.status.value
    return PaymentResponse(
        id=row.id,
        invoice_id=row.invoice_id,
        vendor=row.vendor,
        amount=float(row.amount),
        currency=row.currency,
        status=row.status.value,
        tab=tab,
        due_date=row.due_date,
        scheduled_date=row.scheduled_date,
        paid_date=row.paid_date,
        invoice_approved_by=row.invoice_approved_by,
        approvers=row.approvers or [],
        payment_intent=row.payment_intent,
        failure_reason=row.failure_reason,
        vendor_payout_status=vendor_payout_status,
        vendor_payout_method_type=vendor_payout_method_type,
        execution_readiness_status=execution_readiness_status,
        execution_blocking_reason=execution_blocking_reason,
    )


async def ensure_payment_for_invoice(db: AsyncSession, invoice: Invoice) -> Payment | None:
    from app.services.purchase_document_service import is_commercial_purchase_invoice
    from app.services.vendor_payout_method_service import resolve_vendor_registry_id_for_invoice

    if not is_commercial_purchase_invoice(invoice):
        return None
    if invoice.status != InvoiceStatus.PROCESSED:
        return None
    if invoice.due_date is None or invoice.total is None or invoice.total <= 0:
        return None

    vendor_registry_id = await resolve_vendor_registry_id_for_invoice(
        db,
        invoice.tenant_id,
        vendor_name=invoice.vendor,
        storage_vendor_slug=invoice.storage_vendor_slug,
    )

    existing = (
        await db.execute(
            select(Payment).where(
                Payment.tenant_id == invoice.tenant_id,
                Payment.invoice_id == invoice.id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        if existing.amount != invoice.total:
            existing.amount = invoice.total
        if not existing.vendor:
            existing.vendor = invoice.vendor
        if not existing.due_date:
            existing.due_date = invoice.due_date
        if vendor_registry_id is not None:
            existing.vendor_registry_id = vendor_registry_id
        return existing

    payment = Payment(
        tenant_id=invoice.tenant_id,
        invoice_id=invoice.id,
        vendor_registry_id=vendor_registry_id,
        vendor=invoice.vendor,
        amount=invoice.total,
        currency=invoice.currency or "AUD",
        due_date=invoice.due_date,
        status=PaymentStatus.QUEUE,
        approvers=_payment_tier_approvers(invoice.total),
    )
    db.add(payment)
    await db.flush()
    return payment


async def list_payments(
    db: AsyncSession,
    tenant_id: int,
    *,
    status: str | None = None,
) -> list[PaymentResponse]:
    from app.services.payment_execution_readiness_service import derive_execution_eligibility
    from app.services.stripe_service import get_stripe_readiness_for_tenant
    from app.services.vendor_payout_method_service import payout_summary_for_payments

    stmt = select(Payment).where(Payment.tenant_id == tenant_id).order_by(Payment.created_at.desc())
    if status:
        stmt = stmt.where(Payment.status == PaymentStatus(status))
    rows = (await db.execute(stmt)).scalars().all()

    summaries = await payout_summary_for_payments(db, tenant_id, rows)
    stripe = await get_stripe_readiness_for_tenant(db, tenant_id)
    responses: list[PaymentResponse] = []
    for row, summary in zip(rows, summaries, strict=True):
        eligibility_status, eligibility_reason = derive_execution_eligibility(
            row,
            stripe=stripe,
            vendor_payout_status=summary.get("status"),
            vendor_payout_method_type=summary.get("method_type"),
        )
        responses.append(
            payment_to_response(
                row,
                vendor_payout_status=summary.get("status"),
                vendor_payout_method_type=summary.get("method_type"),
                execution_readiness_status=eligibility_status,
                execution_blocking_reason=eligibility_reason,
            )
        )
    return responses


async def update_payment_status(
    db: AsyncSession,
    tenant_id: int,
    payment_id: int,
    body: PaymentStatusUpdate,
) -> PaymentResponse:
    row = (
        await db.execute(
            select(Payment).where(Payment.id == payment_id, Payment.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise LookupError("Payment not found")

    new_status = PaymentStatus(body.status)
    row.status = new_status
    if body.scheduled_date is not None:
        row.scheduled_date = body.scheduled_date
    if body.payment_intent is not None:
        row.payment_intent = body.payment_intent
    if body.failure_reason is not None:
        row.failure_reason = body.failure_reason
    if new_status == PaymentStatus.PAID:
        row.paid_date = datetime.now(timezone.utc)

    from app.services.payment_execution_readiness_service import derive_execution_eligibility
    from app.services.stripe_service import get_stripe_readiness_for_tenant
    from app.services.vendor_payout_method_service import payout_summary_for_payments

    summaries = await payout_summary_for_payments(db, tenant_id, [row])
    summary = summaries[0] if summaries else {}
    stripe = await get_stripe_readiness_for_tenant(db, tenant_id)
    eligibility_status, eligibility_reason = derive_execution_eligibility(
        row,
        stripe=stripe,
        vendor_payout_status=summary.get("status"),
        vendor_payout_method_type=summary.get("method_type"),
    )
    return payment_to_response(
        row,
        vendor_payout_status=summary.get("status"),
        vendor_payout_method_type=summary.get("method_type"),
        execution_readiness_status=eligibility_status,
        execution_blocking_reason=eligibility_reason,
    )


async def wallet_summary(db: AsyncSession, tenant_id: int) -> WalletSummaryResponse:
    rows = (
        await db.execute(
            select(Payment)
            .where(Payment.tenant_id == tenant_id)
            .order_by(Payment.id.desc())
        )
    ).scalars().all()

    paid_total = Decimal("0")
    open_total = Decimal("0")
    last_paid: datetime | None = None
    transactions: list[WalletTransactionResponse] = []

    for row in rows:
        amount = Decimal(str(row.amount or 0))
        if row.status == PaymentStatus.PAID:
            paid_total += amount
            if row.paid_date and (last_paid is None or row.paid_date > last_paid):
                last_paid = row.paid_date
            transactions.append(
                WalletTransactionResponse(
                    id=str(row.id),
                    label=f"{row.vendor or 'Vendor'} payment",
                    delta=-float(amount),
                )
            )
        elif row.status in _OPEN_STATUSES:
            open_total += amount
            transactions.append(
                WalletTransactionResponse(
                    id=str(row.id),
                    label=f"{row.vendor or 'Vendor'} queued",
                    delta=0.0,
                )
            )

    balance = float(paid_total + open_total)
    available = float(open_total)
    last_top_up = last_paid.date().isoformat() if last_paid else "—"
    return WalletSummaryResponse(
        balance=round(balance, 2),
        available=round(available, 2),
        last_top_up=last_top_up,
        transactions=transactions[:6],
    )


async def payments_queue_count(db: AsyncSession, tenant_id: int) -> int:
    return (
        await db.execute(
            select(func.count(Payment.id)).where(
                Payment.tenant_id == tenant_id,
                Payment.status.in_(_OPEN_STATUSES),
            )
        )
    ).scalar() or 0
