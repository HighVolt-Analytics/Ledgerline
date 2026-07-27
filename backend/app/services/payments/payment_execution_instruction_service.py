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
from app.models.tenant import Tenant
from app.schemas.payment import (
    PaymentExecutionInstructionExportResponse,
    PaymentExecutionInstructionResponse,
    PaymentMarkPaidManualRequest,
    PaymentResponse,
)
from app.services.payments.payment_execution_auth import (
    PaymentExecutionUnauthorizedError,
    require_payment_execution_role,
)
from app.services.payments.payment_execution_rules import (
    LIMIT_BLOCK_MESSAGE,
    TENANT_DISABLED_MESSAGE,
    VENDOR_NOT_VERIFIED_MESSAGE,
    check_payment_manual_execution_limit,
    manual_instruction_eligible,
    vendor_payout_method_verified,
)
from app.services.payments.payment_execution_readiness_service import (
    _build_readiness_checks,
    _default_payout_method,
    _resolve_vendor_registry_id,
    validate_payment_execution_readiness,
)
from app.services.payments.payment_service import payment_to_response
from app.services.payments.stripe_service import get_stripe_readiness_for_tenant
from app.services.master_data.vendor_payout_method_service import payout_summary_for_payments
from app.tenant_settings import tenant_payment_execution_disabled


class PaymentExecutionBlockedError(Exception):
    """Execution blocked by safety gate or business rules."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "blocked",
        safety_gate: bool = False,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
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


async def tenant_execution_enabled(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> tuple[bool, Tenant | None]:
    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if tenant is None:
        return False, None
    if tenant_payment_execution_disabled(tenant):
        return False, tenant
    return True, tenant


def _manual_eligible_from_checks(
    payment: Payment,
    *,
    checks,
    method: VendorPaymentMethod | None,
    tenant_enabled: bool,
) -> tuple[bool, str | None]:
    return manual_instruction_eligible(
        payment,
        approval_ready_flag=checks.approval_ready,
        amount_ready=checks.amount_ready,
        method=method,
        tenant_enabled=tenant_enabled,
    )


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


async def _assert_execution_preconditions(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    ctx: Any | None = None,
    actor: dict[str, Any] | None = None,
) -> Tenant | None:
    allowed, reason = check_manual_execution_safety_gate()
    if not allowed:
        raise PaymentExecutionBlockedError(
            reason or "Manual execution blocked",
            reason_code="safety_gate",
            safety_gate=True,
        )

    tenant_enabled, tenant = await tenant_execution_enabled(db, tenant_id)
    if not tenant_enabled:
        raise PaymentExecutionBlockedError(
            TENANT_DISABLED_MESSAGE,
            reason_code="tenant_disabled",
        )

    if ctx is not None:
        require_payment_execution_role(ctx)
    elif actor is not None:
        from app.services.payments.payment_execution_auth import PAYMENT_EXECUTION_ROLES

        role = str(actor.get("role") or "").strip().lower()
        if role and role not in PAYMENT_EXECUTION_ROLES:
            raise PaymentExecutionUnauthorizedError(
                "Payment execution requires Tenant Admin or Approver role"
            )

    return tenant


async def create_payment_execution_instruction(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    payment_id: int,
    *,
    actor: dict[str, Any],
    ctx: Any | None = None,
) -> tuple[PaymentExecutionInstructionResponse, bool]:
    """Create a read-only manual payment instruction. Idempotent when one already exists."""
    await _assert_execution_preconditions(db, tenant_id, ctx=ctx, actor=actor)

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

    await validate_payment_execution_readiness(
        db,
        tenant_id,
        payment_id,
        actor=actor,
        ctx=ctx,
    )

    checks = await _build_readiness_checks(db, payment)
    vendor_registry_id = await _resolve_vendor_registry_id(db, payment)
    method = (
        await _default_payout_method(db, tenant_id, vendor_registry_id)
        if vendor_registry_id is not None
        else None
    )
    tenant_enabled, _ = await tenant_execution_enabled(db, tenant_id)
    eligible, block_reason = _manual_eligible_from_checks(
        payment,
        checks=checks,
        method=method,
        tenant_enabled=tenant_enabled,
    )
    if not eligible:
        if block_reason == LIMIT_BLOCK_MESSAGE:
            raise PaymentExecutionBlockedError(block_reason, reason_code="limit_exceeded")
        if block_reason == VENDOR_NOT_VERIFIED_MESSAGE:
            raise ValueError(VENDOR_NOT_VERIFIED_MESSAGE)
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
        currency=(payment.currency or "USD").upper(),
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
        disclaimer=(
            "LedgerLink does not move funds. Execute this payment manually outside LedgerLink "
            "from the client-owned bank or wallet."
        ),
    )


async def mark_payment_paid_manual(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    payment_id: int,
    body: PaymentMarkPaidManualRequest,
    *,
    actor: dict[str, Any],
    ctx: Any | None = None,
) -> tuple[PaymentResponse, bool]:
    """Record manual paid status only — no money movement."""
    await _assert_execution_preconditions(db, tenant_id, ctx=ctx, actor=actor)

    reference = (body.reference or "").strip()
    if not reference:
        raise ValueError("A manual payment reference is required")

    proof_reference = (body.proof_reference or "").strip()
    if not proof_reference:
        raise ValueError("Proof of payment reference is required")

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

    limit_ok, limit_reason, _ = check_payment_manual_execution_limit(payment)
    if not limit_ok:
        raise PaymentExecutionBlockedError(limit_reason or LIMIT_BLOCK_MESSAGE, reason_code="limit_exceeded")

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

    if instruction is None or instruction.status != "instruction_created":
        raise ValueError("Create a payment instruction before marking paid manually")

    payment.status = PaymentStatus.PAID
    payment.payment_intent = reference
    payment.paid_date = datetime.combine(body.paid_date, datetime.min.time(), tzinfo=timezone.utc)

    from decimal import Decimal

    from app.services.payments.journal_fx import resolve_payment_fx, round_money
    from app.models.tenant import Tenant
    from app.tenant_settings import tenant_currency

    if body.bank_payment_amount is not None:
        payment.bank_payment_amount = round_money(Decimal(str(body.bank_payment_amount)))
    if body.payment_fx_rate is not None:
        payment.payment_fx_rate = Decimal(str(body.payment_fx_rate))

    tenant = await db.get(Tenant, tenant_id)
    base_currency = tenant_currency(tenant)
    rate, bank_amt, variance, _source = resolve_payment_fx(
        payment, base_currency=base_currency
    )
    if rate is not None and payment.payment_fx_rate is None:
        payment.payment_fx_rate = rate
    if bank_amt is not None and payment.bank_payment_amount is None:
        payment.bank_payment_amount = bank_amt
    if variance is not None:
        payment.fx_variance = variance

    instruction.proof_reference = proof_reference
    instruction.marked_paid_at = datetime.now(timezone.utc)
    actor_user_id = actor.get("user_id")
    if actor_user_id is not None:
        instruction.marked_paid_by_user_id = int(actor_user_id)
    if body.note:
        instruction.note = body.note.strip()

    await db.flush()
    from app.services.payments.settlement_service import post_payment_settlement_journal

    await post_payment_settlement_journal(db, payment)
    return await _payment_response_with_instruction(db, tenant_id, payment), True


async def _payment_response_with_instruction(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    payment: Payment,
) -> PaymentResponse:
    from app.services.payments.payment_execution_readiness_service import derive_execution_eligibility

    summaries = await payout_summary_for_payments(db, tenant_id, [payment])
    summary = summaries[0] if summaries else {}
    stripe = await get_stripe_readiness_for_tenant(db, tenant_id)
    instructions = await instructions_for_payments(db, tenant_id, [payment.id])
    instruction = instructions.get(payment.id)
    settings = get_settings()
    tenant_enabled, _ = await tenant_execution_enabled(db, tenant_id)

    manual_eligible = False
    manual_block_reason: str | None = None
    if payment.status == PaymentStatus.SCHEDULED and instruction is None:
        checks = await _build_readiness_checks(db, payment, stripe=stripe)
        vendor_registry_id = await _resolve_vendor_registry_id(db, payment)
        method = (
            await _default_payout_method(db, tenant_id, vendor_registry_id)
            if vendor_registry_id is not None
            else None
        )
        manual_eligible, manual_block_reason = _manual_eligible_from_checks(
            payment,
            checks=checks,
            method=method,
            tenant_enabled=tenant_enabled,
        )

    eligibility_status, eligibility_reason = derive_execution_eligibility(
        payment,
        stripe=stripe,
        vendor_payout_status=summary.get("status"),
        vendor_payout_method_type=summary.get("method_type"),
        has_instruction=instruction is not None,
        manual_execution_enabled=settings.payment_manual_execution_enabled,
        manual_instruction_eligible=manual_eligible,
        tenant_execution_enabled=tenant_enabled,
        manual_block_reason=manual_block_reason,
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


__all__ = [
    "PaymentExecutionBlockedError",
    "create_payment_execution_instruction",
    "export_payment_execution_instruction",
    "mark_payment_paid_manual",
]
