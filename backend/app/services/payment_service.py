"""Payment disbursement workflow (Phase F)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.schemas.payment import (
    PaymentExecutionInstructionResponse,
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


async def _payment_response_with_eligibility(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    row: Payment,
) -> PaymentResponse:
    from app.config import get_settings
    from app.services.payment_execution_instruction_service import (
        _instruction_to_response,
        instructions_for_payments,
        manual_instruction_eligible,
    )
    from app.services.payment_execution_readiness_service import (
        _build_readiness_checks,
        _default_payout_method,
        _resolve_vendor_registry_id,
        derive_execution_eligibility,
    )
    from app.services.stripe_service import get_stripe_readiness_for_tenant
    from app.services.vendor_payout_method_service import payout_summary_for_payments

    summaries = await payout_summary_for_payments(db, tenant_id, [row])
    summary = summaries[0] if summaries else {}
    stripe = await get_stripe_readiness_for_tenant(db, tenant_id)
    instructions = await instructions_for_payments(db, tenant_id, [row.id])
    instruction = instructions.get(row.id)
    settings = get_settings()

    manual_eligible = False
    if row.status == PaymentStatus.SCHEDULED and instruction is None:
        checks = await _build_readiness_checks(db, row, stripe=stripe)
        vendor_registry_id = await _resolve_vendor_registry_id(db, row)
        method = (
            await _default_payout_method(db, tenant_id, vendor_registry_id)
            if vendor_registry_id is not None
            else None
        )
        manual_eligible, _ = manual_instruction_eligible(row, checks=checks, method=method)

    eligibility_status, eligibility_reason = derive_execution_eligibility(
        row,
        stripe=stripe,
        vendor_payout_status=summary.get("status"),
        vendor_payout_method_type=summary.get("method_type"),
        has_instruction=instruction is not None,
        manual_execution_enabled=settings.payment_manual_execution_enabled,
        manual_instruction_eligible=manual_eligible,
    )
    instruction_response = (
        _instruction_to_response(instruction) if instruction is not None else None
    )
    return payment_to_response(
        row,
        vendor_payout_status=summary.get("status"),
        vendor_payout_method_type=summary.get("method_type"),
        execution_readiness_status=eligibility_status,
        execution_blocking_reason=eligibility_reason,
        execution_instruction=instruction_response,
    )


async def approve_payment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    payment_id: int,
    *,
    actor: dict[str, Any],
) -> tuple[PaymentResponse, bool]:
    """Single approver workflow: awaiting -> scheduled with logged-in user as approver."""
    row = (
        await db.execute(
            select(Payment).where(
                Payment.id == payment_id,
                Payment.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise LookupError("Payment not found")

    if row.status == PaymentStatus.SCHEDULED:
        return await _payment_response_with_eligibility(db, tenant_id, row), False

    if row.status != PaymentStatus.AWAITING:
        raise ValueError(
            f"Payment status '{row.status.value}' cannot be approved; "
            "submit the payment for approval first."
        )

    actor_user_id = actor.get("user_id")
    actor_name = str(actor.get("name") or actor.get("email") or "Approver").strip()
    actor_email = str(actor.get("email") or "").strip()
    actor_id = str(actor_user_id) if actor_user_id is not None else actor_email or actor_name

    row.status = PaymentStatus.SCHEDULED
    row.scheduled_date = date.today()
    row.approvers = [
        {
            "id": actor_id,
            "name": actor_name,
            "role": "Approver",
            "state": "approved",
        }
    ]
    await db.flush()
    return await _payment_response_with_eligibility(db, tenant_id, row), True


def payment_to_response(
    row: Payment,
    *,
    vendor_payout_status: str | None = None,
    vendor_payout_method_type: str | None = None,
    execution_readiness_status: str | None = None,
    execution_blocking_reason: str | None = None,
    execution_instruction: PaymentExecutionInstructionResponse | None = None,
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
        execution_instruction=execution_instruction,
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
    tenant_id: uuid.UUID,
    *,
    status: str | None = None,
) -> list[PaymentResponse]:
    from app.config import get_settings
    from app.services.payment_execution_instruction_service import (
        _instruction_to_response,
        instructions_for_payments,
        manual_instruction_eligible,
    )
    from app.services.payment_execution_readiness_service import (
        _build_readiness_checks,
        _default_payout_method,
        _resolve_vendor_registry_id,
        derive_execution_eligibility,
    )
    from app.services.stripe_service import get_stripe_readiness_for_tenant
    from app.services.vendor_payout_method_service import payout_summary_for_payments

    stmt = select(Payment).where(Payment.tenant_id == tenant_id).order_by(Payment.created_at.desc())
    if status:
        stmt = stmt.where(Payment.status == PaymentStatus(status))
    rows = (await db.execute(stmt)).scalars().all()

    summaries = await payout_summary_for_payments(db, tenant_id, rows)
    stripe = await get_stripe_readiness_for_tenant(db, tenant_id)
    instructions = await instructions_for_payments(db, tenant_id, [row.id for row in rows])
    settings = get_settings()
    responses: list[PaymentResponse] = []
    for row, summary in zip(rows, summaries, strict=True):
        instruction = instructions.get(row.id)
        manual_eligible = False
        if row.status == PaymentStatus.SCHEDULED and instruction is None:
            checks = await _build_readiness_checks(db, row, stripe=stripe)
            vendor_registry_id = await _resolve_vendor_registry_id(db, row)
            method = (
                await _default_payout_method(db, tenant_id, vendor_registry_id)
                if vendor_registry_id is not None
                else None
            )
            manual_eligible, _ = manual_instruction_eligible(row, checks=checks, method=method)

        eligibility_status, eligibility_reason = derive_execution_eligibility(
            row,
            stripe=stripe,
            vendor_payout_status=summary.get("status"),
            vendor_payout_method_type=summary.get("method_type"),
            has_instruction=instruction is not None,
            manual_execution_enabled=settings.payment_manual_execution_enabled,
            manual_instruction_eligible=manual_eligible,
        )
        instruction_response = (
            _instruction_to_response(instruction) if instruction is not None else None
        )
        responses.append(
            payment_to_response(
                row,
                vendor_payout_status=summary.get("status"),
                vendor_payout_method_type=summary.get("method_type"),
                execution_readiness_status=eligibility_status,
                execution_blocking_reason=eligibility_reason,
                execution_instruction=instruction_response,
            )
        )
    return responses


async def update_payment_status(
    db: AsyncSession,
    tenant_id: uuid.UUID,
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

    await db.flush()
    return await _payment_response_with_eligibility(db, tenant_id, row)


async def wallet_summary(db: AsyncSession, tenant_id: uuid.UUID) -> WalletSummaryResponse:
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


async def payments_queue_count(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count(Payment.id)).where(
                Payment.tenant_id == tenant_id,
                Payment.status.in_(_OPEN_STATUSES),
            )
        )
    ).scalar() or 0
