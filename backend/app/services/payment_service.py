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
    )


async def ensure_payment_for_invoice(db: AsyncSession, invoice: Invoice) -> Payment | None:
    from app.services.purchase_document_service import is_commercial_purchase_invoice

    if not is_commercial_purchase_invoice(invoice):
        return None
    if invoice.status != InvoiceStatus.PROCESSED:
        return None
    if invoice.due_date is None or invoice.total is None or invoice.total <= 0:
        return None

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
        return existing

    payment = Payment(
        tenant_id=invoice.tenant_id,
        invoice_id=invoice.id,
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
    from app.services.vendor_payout_method_service import (
        _normalize_vendor_key,
        default_payout_lookup_by_vendor_names,
    )

    stmt = select(Payment).where(Payment.tenant_id == tenant_id).order_by(Payment.created_at.desc())
    if status:
        stmt = stmt.where(Payment.status == PaymentStatus(status))
    rows = (await db.execute(stmt)).scalars().all()

    payout_lookup = await default_payout_lookup_by_vendor_names(
        db,
        tenant_id,
        [row.vendor for row in rows],
    )
    responses: list[PaymentResponse] = []
    for row in rows:
        key = _normalize_vendor_key(row.vendor)
        if not key:
            summary: dict[str, str | None] = {}
        elif key in payout_lookup:
            summary = payout_lookup[key]
        else:
            summary = {"status": "not_configured", "method_type": None}
        responses.append(
            payment_to_response(
                row,
                vendor_payout_status=summary.get("status"),
                vendor_payout_method_type=summary.get("method_type"),
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
    return payment_to_response(row)


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
