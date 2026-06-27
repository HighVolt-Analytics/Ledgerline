"""Manual payment execution instruction orchestration — no Stripe money movement."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.payment import Payment, PaymentStatus
from app.models.payment_execution_instruction import PaymentExecutionInstruction
from app.models.stripe_payments import VendorPaymentMethod
from app.schemas.payment import (
    PaymentExecutionInstructionExportResponse,
    PaymentExecutionInstructionResponse,
    PaymentMarkPaidManualRequest,
    PaymentResponse,
)
from app.services.payment_execution_readiness_service import (
    _approval_ready,
    _build_readiness_checks,
    _default_payout_method,
    _resolve_vendor_registry_id,
    validate_payment_execution_readiness,
)
from app.services.payment_service import payment_to_response
from app.services.stripe_service import get_stripe_readiness_for_tenant
from app.services.vendor_payout_method_service import payout_summary_for_payments


class PaymentExecutionBlockedError(Exception):
    """Execution blocked by safety gate or business rules."""

    def __init__(self, message: str, *, safety_gate: bool = False) -> None:
        super().__init__(message)
        self.safety_gate = safety_gate


def format_payout_method_label(method: VendorPaymentMethod | None) -> str:
    if method is None:
        return "Not configured"
    type_labels = {
        "manual_bank": "Manual bank transfer",
        "stripe_connected_account": "Stripe connected account",
    }
    method_type = method.method_type or ""
    type_label = type_labels.get(method_type, method_type.replace("_", " "))
    display = (method.display_label or "").strip()
    if display:
        return f"{display} ({type_label})"
    return type_label


def check_manual_execution_safety_gate() -> tuple[bool, str | None]:
    settings = get_settings()
    if settings.payment_execution_disabled:
        return False, "Payment execution is disabled by safety gate (PAYMENT_EXECUTION_DISABLED)"
    if not settings.payment_manual_execution_enabled:
        return False, "Manual payment execution is not enabled (PAYMENT_MANUAL_EXECUTION_ENABLED)"
    return True, None


def _instruction_to_response(row: PaymentExecutionInstruction) -> PaymentExecutionInstructionResponse:
    return PaymentExecutionInstructionResponse(
        id=row.id,
        payment_id=row.payment_id,
        instruction_reference=row.instruction_reference,
        vendor_name=row.vendor_name,
        vendor_payout_method_label=row.vendor_payout_method_label,
        amount=float(row.amount),
        currency=row.currency,
        due_date=row.due_date,
        execution_mode=row.execution_mode,
        status=row.status,
        created_by_name=row.created_by_name,
        created_by_email=row.created_by_email,
        created_at=row.created_at,
    )


async def instructions_for_payments(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    payment_ids: list[int],
) -> dict[int, PaymentExecutionInstruction]:
    if not payment_ids:
        return {}
    rows = (
        await db.execute(
            select(PaymentExecutionInstruction).where(
                PaymentExecutionInstruction.tenant_id == tenant_id,
                PaymentExecutionInstruction.payment_id.in_(payment_ids),
                PaymentExecutionInstruction.status == "instruction_created",
            )
        )
    ).scalars().all()
    return {row.payment_id: row for row in rows}


def manual_instruction_eligible(
    payment: Payment,
    *,
    checks,
    method: VendorPaymentMethod | None,
) -> tuple[bool, str | None]:
    if payment.status != PaymentStatus.SCHEDULED:
        return False, "Payment must be scheduled before creating an instruction"

    if not checks.approval_ready:
        return False, "Payment approval workflow is incomplete"

    if not checks.amount_ready:
        return False, "Payment amount or currency is not valid for execution"

    settings = get_settings()
    amount = Decimal(str(payment.amount or 0))
    limit = Decimal(str(settings.payment_manual_execution_limit_aud))
    if amount > limit:
        return (
            False,
            f"Payment amount exceeds manual execution limit ({settings.payment_manual_execution_limit_aud} AUD)",
        )

    if checks.tenant_stripe_ready and checks.vendor_payout_ready:
        return True, None

    method_type = (method.method_type or "") if method else ""
    status = (method.status or "") if method else ""
    if method_type == "manual_bank" and status == "verified":
        return True, None

    if not checks.tenant_stripe_ready:
        return (
            False,
            "Stripe setup is incomplete; configure a verified manual bank payout method for the vendor",
        )
    if not checks.vendor_payout_ready:
        return False, "Vendor payout method is not verified"
    return False, "Payment is not eligible for manual instruction"


async def create_payment_execution_instruction(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    payment_id: int,
    *,
    actor: dict[str, Any],
) -> tuple[PaymentExecutionInstructionResponse, bool]:
    """Create a read-only manual payment instruction. Idempotent when one already exists."""
    allowed, reason = check_manual_execution_safety_gate()
    if not allowed:
        raise PaymentExecutionBlockedError(reason or "Manual execution blocked", safety_gate=True)

    payment = (
        await db.execute(
            select(Payment).where(
                Payment.id == payment_id,
                Payment.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if payment is None:
        raise LookupError("Payment not found")

    existing = (
        await db.execute(
            select(PaymentExecutionInstruction).where(
                PaymentExecutionInstruction.tenant_id == tenant_id,
                PaymentExecutionInstruction.payment_id == payment_id,
                PaymentExecutionInstruction.status == "instruction_created",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return _instruction_to_response(existing), False

    if payment.status != PaymentStatus.SCHEDULED:
        raise ValueError(
            f"Payment status '{payment.status.value}' cannot receive an execution instruction; "
            "approve the payment first."
        )

    await validate_payment_execution_readiness(db, tenant_id, payment_id, actor=actor)

    checks = await _build_readiness_checks(db, payment)
    vendor_registry_id = await _resolve_vendor_registry_id(db, payment)
    method = (
        await _default_payout_method(db, tenant_id, vendor_registry_id)
        if vendor_registry_id is not None
        else None
    )
    eligible, block_reason = manual_instruction_eligible(payment, checks=checks, method=method)
    if not eligible:
        raise ValueError(block_reason or "Payment is not eligible for manual instruction")

    reference = f"LL-MPI-{payment_id}-{uuid.uuid4().hex[:8].upper()}"
    actor_user_id = actor.get("user_id")
    actor_name = str(actor.get("name") or actor.get("email") or "User").strip()
    actor_email = str(actor.get("email") or "").strip() or None

    row = PaymentExecutionInstruction(
        tenant_id=tenant_id,
        payment_id=payment_id,
        instruction_reference=reference,
        execution_mode="manual_instruction",
        status="instruction_created",
        vendor_name=payment.vendor,
        vendor_payout_method_label=format_payout_method_label(method),
        amount=Decimal(str(payment.amount)),
        currency=(payment.currency or "AUD").upper(),
        due_date=payment.due_date,
        created_by_user_id=int(actor_user_id) if actor_user_id is not None else None,
        created_by_name=actor_name,
        created_by_email=actor_email,
    )
    db.add(row)
    await db.flush()
    return _instruction_to_response(row), True


async def get_payment_execution_instruction(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    payment_id: int,
) -> PaymentExecutionInstructionResponse:
    row = (
        await db.execute(
            select(PaymentExecutionInstruction).where(
                PaymentExecutionInstruction.tenant_id == tenant_id,
                PaymentExecutionInstruction.payment_id == payment_id,
                PaymentExecutionInstruction.status == "instruction_created",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise LookupError("Payment execution instruction not found")
    return _instruction_to_response(row)


async def export_payment_execution_instruction(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    payment_id: int,
) -> PaymentExecutionInstructionExportResponse:
    instruction = await get_payment_execution_instruction(db, tenant_id, payment_id)
    return PaymentExecutionInstructionExportResponse(
        payment_id=instruction.payment_id,
        instruction_reference=instruction.instruction_reference,
        vendor_name=instruction.vendor_name,
        vendor_payout_method_label=instruction.vendor_payout_method_label,
        amount=instruction.amount,
        currency=instruction.currency,
        due_date=instruction.due_date,
        execution_mode=instruction.execution_mode,
        status=instruction.status,
        created_by=instruction.created_by_name,
        created_at=instruction.created_at,
        export_format="json",
        disclaimer="LedgerLink does not move funds. Execute this payment manually outside LedgerLink.",
    )


async def mark_payment_paid_manual(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    payment_id: int,
    body: PaymentMarkPaidManualRequest,
    *,
    actor: dict[str, Any],
) -> tuple[PaymentResponse, bool]:
    """Record manual paid status only — no money movement."""
    _ = actor
    allowed, reason = check_manual_execution_safety_gate()
    if not allowed:
        raise PaymentExecutionBlockedError(reason or "Manual execution blocked", safety_gate=True)

    reference = (body.reference or "").strip()
    if not reference:
        raise ValueError("A manual payment reference is required")

    payment = (
        await db.execute(
            select(Payment).where(
                Payment.id == payment_id,
                Payment.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if payment is None:
        raise LookupError("Payment not found")

    if payment.status == PaymentStatus.PAID:
        return await _payment_response_with_instruction(db, tenant_id, payment), False

    instruction = (
        await db.execute(
            select(PaymentExecutionInstruction).where(
                PaymentExecutionInstruction.tenant_id == tenant_id,
                PaymentExecutionInstruction.payment_id == payment_id,
            )
        )
    ).scalar_one_or_none()

    if payment.status != PaymentStatus.SCHEDULED:
        raise ValueError(
            f"Payment status '{payment.status.value}' cannot be marked paid manually"
        )

    if instruction is not None and instruction.status != "instruction_created":
        raise ValueError("Payment instruction is not in instruction_created status")

    payment.status = PaymentStatus.PAID
    payment.payment_intent = reference
    if body.paid_date is not None:
        payment.paid_date = datetime.combine(body.paid_date, datetime.min.time(), tzinfo=timezone.utc)
    else:
        payment.paid_date = datetime.now(timezone.utc)

    if body.note:
        instruction.note = body.note.strip()

    await db.flush()
    return await _payment_response_with_instruction(db, tenant_id, payment), True


async def _payment_response_with_instruction(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    payment: Payment,
) -> PaymentResponse:
    from app.services.payment_execution_readiness_service import derive_execution_eligibility

    summaries = await payout_summary_for_payments(db, tenant_id, [payment])
    summary = summaries[0] if summaries else {}
    stripe = await get_stripe_readiness_for_tenant(db, tenant_id)
    instructions = await instructions_for_payments(db, tenant_id, [payment.id])
    instruction = instructions.get(payment.id)
    settings = get_settings()

    manual_eligible = False
    if payment.status == PaymentStatus.SCHEDULED and instruction is None:
        checks = await _build_readiness_checks(db, payment, stripe=stripe)
        vendor_registry_id = await _resolve_vendor_registry_id(db, payment)
        method = (
            await _default_payout_method(db, tenant_id, vendor_registry_id)
            if vendor_registry_id is not None
            else None
        )
        manual_eligible, _ = manual_instruction_eligible(payment, checks=checks, method=method)

    eligibility_status, eligibility_reason = derive_execution_eligibility(
        payment,
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
        payment,
        vendor_payout_status=summary.get("status"),
        vendor_payout_method_type=summary.get("method_type"),
        execution_readiness_status=eligibility_status,
        execution_blocking_reason=eligibility_reason,
        execution_instruction=instruction_response,
    )
