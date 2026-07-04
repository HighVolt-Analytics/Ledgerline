"""Dry-run payment execution readiness — no Stripe money movement."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.payment import Payment, PaymentStatus
from app.models.stripe_payments import VendorPaymentMethod
from app.models.tenant import Tenant
from app.services.payments.payment_execution_auth import actor_can_execute_manual_payment
from app.services.payments.payment_execution_rules import (
    LIMIT_BLOCK_MESSAGE,
    TENANT_DISABLED_MESSAGE,
    VENDOR_NOT_VERIFIED_MESSAGE,
    approval_ready,
    check_payment_manual_execution_limit,
    vendor_payout_method_verified,
)
from app.services.payments.payment_rail_service import (
    get_selected_payment_rail,
    payment_rail_context,
    validate_payment_rail_readiness,
)
from app.services.payments.stripe_global_payouts_service import get_stripe_global_payouts_readiness
from app.services.payments.stripe_service import StripeReadiness, get_stripe_readiness_for_tenant
from app.services.master_data.vendor_payout_method_service import (
    PAYOUT_METHOD_TYPES,
    resolve_vendor_registry_id_for_invoice,
)
from app.tenant_settings import tenant_payment_execution_disabled

_SUPPORTED_CURRENCIES = frozenset({"AUD", "USD"})
_EXECUTION_SUPPORTED_METHOD_TYPES = frozenset(
    {"manual_bank", "stripe_connected_account"},
)


@dataclass(frozen=True)
class PaymentExecutionReadiness:
    payment_id: int
    can_execute: bool
    execution_mode: str
    blocking_reasons: list[str]
    warnings: list[str]
    tenant_stripe_ready: bool
    vendor_payout_ready: bool
    approval_ready: bool
    amount_ready: bool
    manual_execution_ready: bool
    role_ready: bool | None
    limit_ready: bool
    tenant_execution_enabled: bool
    recommended_action: str | None
    payments_execution_enabled: bool
    selected_payment_rail: str = "manual_instruction"
    stripe_global_payouts_ready: bool = False
    stripe_global_payouts_blocking_reason: str | None = None
    payment_rail_ready: bool = False
    payment_rail_recommended_action: str | None = None
    app_env: str = "preview"
    stripe_mode: str = "test"
    live_execution_enabled: bool = False


@dataclass
class _ReadinessChecks:
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tenant_stripe_ready: bool = False
    vendor_payout_ready: bool = False
    approval_ready: bool = False
    amount_ready: bool = False
    limit_ready: bool = True
    tenant_execution_enabled: bool = True
    recommended_action: str | None = None


def _approval_ready(payment: Payment) -> bool:
    return approval_ready(payment)


async def _resolve_vendor_registry_id(
    db: AsyncSession,
    payment: Payment,
) -> int | None:
    if payment.vendor_registry_id is not None:
        return payment.vendor_registry_id
    return await resolve_vendor_registry_id_for_invoice(
        db,
        payment.tenant_id,
        vendor_name=payment.vendor,
        storage_vendor_slug=None,
    )


async def _default_payout_method(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    vendor_registry_id: int,
) -> VendorPaymentMethod | None:
    rows = (
        await db.execute(
            select(VendorPaymentMethod).where(
                VendorPaymentMethod.tenant_id == tenant_id,
                VendorPaymentMethod.vendor_id == vendor_registry_id,
            )
        )
    ).scalars().all()
    active = [row for row in rows if (row.status or "") != "disabled"]
    default = next((row for row in active if row.is_default), None)
    if default is None and active:
        default = active[0]
    return default


def _evaluate_stripe_readiness(
    checks: _ReadinessChecks,
    stripe: StripeReadiness,
) -> None:
    if not stripe.connected:
        checks.blocking_reasons.append("Stripe account is not connected")
        checks.recommended_action = stripe.recommended_action
        return

    if stripe.onboarding_status in ("pending", "action_required") or stripe.blocking_reason == (
        "Stripe onboarding is incomplete"
    ):
        checks.blocking_reasons.append("Stripe onboarding is incomplete")

    if not stripe.charges_enabled:
        checks.blocking_reasons.append("Stripe charges are disabled")

    if not stripe.payouts_enabled:
        checks.blocking_reasons.append("Stripe payouts are disabled")

    checks.tenant_stripe_ready = (
        stripe.connected
        and stripe.charges_enabled
        and stripe.payouts_enabled
        and stripe.blocking_reason is None
    )
    if not checks.tenant_stripe_ready and stripe.recommended_action:
        checks.recommended_action = stripe.recommended_action


def _evaluate_vendor_payout(
    checks: _ReadinessChecks,
    *,
    vendor_registry_id: int | None,
    method: VendorPaymentMethod | None,
    linked_via_fallback: bool,
) -> None:
    if vendor_registry_id is None:
        checks.blocking_reasons.append("Payment is not linked to a vendor registry record")
        if checks.recommended_action is None:
            checks.recommended_action = "Register or link the vendor in Vendors before payout."
        return

    if linked_via_fallback:
        checks.warnings.append(
            "Vendor link resolved by name only; save vendor_registry_id on the payment when possible."
        )

    if method is None:
        checks.blocking_reasons.append("Vendor has no default payout method configured")
        if checks.recommended_action is None:
            checks.recommended_action = "Verify vendor payout method"
        return

    method_type = method.method_type or ""
    if method_type not in PAYOUT_METHOD_TYPES:
        checks.blocking_reasons.append(f"Vendor payout method type is unsupported: {method_type}")
    elif method_type not in _EXECUTION_SUPPORTED_METHOD_TYPES:
        checks.blocking_reasons.append(
            f"Vendor payout method type is not enabled for execution: {method_type}"
        )
    elif method_type == "stripe_connected_account" and not method.stripe_account_id:
        checks.blocking_reasons.append(
            "Vendor Stripe connected account payout method is missing stripe_account_id"
        )

    if not vendor_payout_method_verified(method):
        checks.blocking_reasons.append(VENDOR_NOT_VERIFIED_MESSAGE)
        if checks.recommended_action is None:
            checks.recommended_action = "Verify vendor payout method"

    checks.vendor_payout_ready = vendor_payout_method_verified(method)


async def _build_readiness_checks(
    db: AsyncSession,
    payment: Payment,
    *,
    stripe: StripeReadiness | None = None,
    tenant: Tenant | None = None,
) -> _ReadinessChecks:
    checks = _ReadinessChecks()

    if tenant is None:
        tenant = (
            await db.execute(select(Tenant).where(Tenant.id == payment.tenant_id))
        ).scalar_one_or_none()
    checks.tenant_execution_enabled = not tenant_payment_execution_disabled(tenant)
    if not checks.tenant_execution_enabled:
        checks.blocking_reasons.append(TENANT_DISABLED_MESSAGE)
        checks.recommended_action = TENANT_DISABLED_MESSAGE

    if payment.status in (PaymentStatus.PAID, PaymentStatus.FAILED):
        checks.blocking_reasons.append(
            f"Payment is already {payment.status.value} and cannot be executed"
        )
        return checks

    amount = Decimal(str(payment.amount or 0))
    if amount <= 0:
        checks.blocking_reasons.append("Payment amount must be greater than zero")
    else:
        checks.amount_ready = True

    currency = (payment.currency or "USD").upper()
    if currency not in _SUPPORTED_CURRENCIES:
        checks.blocking_reasons.append(f"Payment currency {currency} is not supported")
        checks.amount_ready = False
    elif checks.amount_ready and not payment.due_date:
        checks.warnings.append("Payment due date is missing; confirm scheduling before execution")

    limit_ok, limit_reason, limit_warnings = check_payment_manual_execution_limit(payment)
    checks.limit_ready = limit_ok
    checks.warnings.extend(limit_warnings)
    if not limit_ok and limit_reason:
        checks.blocking_reasons.append(limit_reason)
        checks.recommended_action = limit_reason

    checks.approval_ready = _approval_ready(payment)
    if not checks.approval_ready:
        if payment.status in (PaymentStatus.QUEUE, PaymentStatus.AWAITING):
            checks.blocking_reasons.append("Payment approval workflow is incomplete")
        else:
            checks.blocking_reasons.append(
                "Payment is not approved for execution (status must be scheduled with approvals complete)"
            )
        if checks.recommended_action is None:
            checks.recommended_action = "Approve payment first"

    stripe_readiness = stripe or await get_stripe_readiness_for_tenant(db, payment.tenant_id)
    _evaluate_stripe_readiness(checks, stripe_readiness)

    vendor_registry_id = await _resolve_vendor_registry_id(db, payment)
    linked_via_fallback = (
        payment.vendor_registry_id is None and vendor_registry_id is not None
    )
    method = (
        await _default_payout_method(db, payment.tenant_id, vendor_registry_id)
        if vendor_registry_id is not None
        else None
    )
    _evaluate_vendor_payout(
        checks,
        vendor_registry_id=vendor_registry_id,
        method=method,
        linked_via_fallback=linked_via_fallback,
    )

    settings = get_settings()
    if settings.stripe_payment_execution_enabled:
        checks.warnings.append(
            "STRIPE_PAYMENTS_EXECUTION_ENABLED is true but real Stripe payout/transfer APIs remain disabled."
        )
    if not settings.payment_manual_execution_enabled:
        checks.warnings.append("Manual payment execution is disabled in server configuration.")

    return checks


def _manual_execution_ready(checks: _ReadinessChecks) -> bool:
    settings = get_settings()
    return (
        settings.payment_manual_execution_enabled
        and not settings.payment_execution_disabled
        and checks.tenant_execution_enabled
        and checks.approval_ready
        and checks.amount_ready
        and checks.limit_ready
        and checks.vendor_payout_ready
    )


def _recommended_action(
    checks: _ReadinessChecks,
    *,
    manual_ready: bool,
    has_instruction: bool,
) -> str | None:
    if has_instruction:
        return "Mark paid manually after client completes external payment"
    if not checks.tenant_execution_enabled:
        return TENANT_DISABLED_MESSAGE
    if not checks.limit_ready:
        return LIMIT_BLOCK_MESSAGE
    if not checks.approval_ready:
        return "Approve payment first"
    if not checks.vendor_payout_ready:
        return "Verify vendor payout method"
    if manual_ready:
        return "Create payment instruction"
    return checks.recommended_action


def _to_readiness_result(
    payment_id: int,
    checks: _ReadinessChecks,
    *,
    role_ready: bool | None = None,
    has_instruction: bool = False,
) -> PaymentExecutionReadiness:
    settings = get_settings()
    manual_ready = _manual_execution_ready(checks)
    can_execute = (
        manual_ready
        and (role_ready is not False)
        and not has_instruction
    )
    stripe_can_execute = (
        not checks.blocking_reasons
        and checks.tenant_stripe_ready
        and checks.vendor_payout_ready
        and checks.approval_ready
        and checks.amount_ready
    )
    recommended = _recommended_action(checks, manual_ready=manual_ready, has_instruction=has_instruction)
    if stripe_can_execute and not manual_ready:
        recommended = (
            "Dry-run validation passed for Stripe rails. Real Stripe execution remains disabled; "
            "use manual payment instruction orchestration."
        )
    rail_ctx = payment_rail_context(settings)
    selected_rail = get_selected_payment_rail(settings)
    gp = get_stripe_global_payouts_readiness(settings)
    rail_ready, _, rail_action = validate_payment_rail_readiness(
        selected_rail,
        global_payouts=gp,
        settings=settings,
    )
    return PaymentExecutionReadiness(
        payment_id=payment_id,
        can_execute=can_execute or stripe_can_execute,
        execution_mode="manual_instruction" if manual_ready else "dry_run",
        blocking_reasons=checks.blocking_reasons,
        warnings=checks.warnings,
        tenant_stripe_ready=checks.tenant_stripe_ready,
        vendor_payout_ready=checks.vendor_payout_ready,
        approval_ready=checks.approval_ready,
        amount_ready=checks.amount_ready,
        manual_execution_ready=manual_ready,
        role_ready=role_ready,
        limit_ready=checks.limit_ready,
        tenant_execution_enabled=checks.tenant_execution_enabled,
        recommended_action=recommended,
        payments_execution_enabled=settings.stripe_payment_execution_enabled,
        selected_payment_rail=rail_ctx["selected_payment_rail"],
        stripe_global_payouts_ready=bool(rail_ctx["stripe_global_payouts_ready"]),
        stripe_global_payouts_blocking_reason=rail_ctx["stripe_global_payouts_blocking_reason"],
        payment_rail_ready=rail_ready,
        payment_rail_recommended_action=rail_action,
        app_env=str(rail_ctx["app_env"]),
        stripe_mode=str(rail_ctx["stripe_mode"]),
        live_execution_enabled=bool(rail_ctx["live_execution_enabled"]),
    )


async def validate_payment_execution_readiness(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    payment_id: int,
    *,
    actor: dict[str, Any] | None = None,
    ctx: Any | None = None,
) -> PaymentExecutionReadiness:
    """Read-only dry-run validation; does not mutate payment or call Stripe money APIs."""
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

    role_ready: bool | None = None
    if ctx is not None:
        role_ready = actor_can_execute_manual_payment(ctx)
        if not role_ready:
            pass  # surfaced via recommended_action in API layer if needed

    from app.models.payment_execution_instruction import PaymentExecutionInstruction

    instructions = (
        await db.execute(
            select(PaymentExecutionInstruction).where(
                PaymentExecutionInstruction.tenant_id == tenant_id,
                PaymentExecutionInstruction.payment_id == payment.id,
                PaymentExecutionInstruction.status == "instruction_created",
            )
        )
    ).scalars().all()
    has_instruction = bool(instructions)

    checks = await _build_readiness_checks(db, payment)
    return _to_readiness_result(
        payment.id,
        checks,
        role_ready=role_ready,
        has_instruction=has_instruction,
    )


def derive_execution_eligibility(
    payment: Payment,
    *,
    stripe: StripeReadiness,
    vendor_payout_status: str | None,
    vendor_payout_method_type: str | None,
    has_instruction: bool = False,
    manual_execution_enabled: bool = False,
    manual_instruction_eligible: bool = False,
    tenant_execution_enabled: bool = True,
    manual_block_reason: str | None = None,
) -> tuple[str, str | None]:
    """Read-only eligibility label for payment list UI."""
    if payment.status == PaymentStatus.PAID:
        return "paid", None
    if payment.status == PaymentStatus.FAILED:
        return "failed", payment.failure_reason

    if payment.status in (PaymentStatus.QUEUE, PaymentStatus.AWAITING):
        return "awaiting_approval", "Complete payment approval workflow"

    if not tenant_execution_enabled:
        return "blocked_tenant_disabled", TENANT_DISABLED_MESSAGE

    if manual_block_reason == LIMIT_BLOCK_MESSAGE:
        return "blocked_limit", LIMIT_BLOCK_MESSAGE

    vendor_verified = vendor_payout_status == "verified"

    if payment.status == PaymentStatus.SCHEDULED:
        if has_instruction:
            return "instruction_created", None

        if manual_execution_enabled and manual_instruction_eligible:
            return "manual_instruction_available", None

        if not vendor_verified:
            if not vendor_payout_status or vendor_payout_status == "not_configured":
                return "blocked_vendor_payout_setup", VENDOR_NOT_VERIFIED_MESSAGE
            return "blocked_vendor_payout_setup", VENDOR_NOT_VERIFIED_MESSAGE

        stripe_ready = (
            stripe.connected
            and stripe.charges_enabled
            and stripe.payouts_enabled
            and stripe.blocking_reason is None
        )
        if manual_execution_enabled and _approval_ready(payment):
            return "manual_instruction_available", None

        if not stripe_ready:
            reason = stripe.blocking_reason or "Stripe setup is incomplete"
            return "blocked_stripe_setup", reason

        if _approval_ready(payment):
            if manual_execution_enabled:
                return "manual_instruction_available", None
            return "ready_dry_run", None
        return "scheduled", "Payment is scheduled but approval chain may be incomplete"

    return "not_ready", None
