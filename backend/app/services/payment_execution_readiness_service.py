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
from app.models.vendor import VendorRegistry
from app.services.stripe_service import StripeReadiness, get_stripe_readiness_for_tenant
from app.services.vendor_payout_method_service import (
    PAYOUT_METHOD_TYPES,
    resolve_vendor_registry_id_for_invoice,
)

_SUPPORTED_CURRENCIES = frozenset({"AUD"})
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
    recommended_action: str | None
    payments_execution_enabled: bool


@dataclass
class _ReadinessChecks:
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tenant_stripe_ready: bool = False
    vendor_payout_ready: bool = False
    approval_ready: bool = False
    amount_ready: bool = False
    recommended_action: str | None = None


def _approval_ready(payment: Payment) -> bool:
    if payment.status != PaymentStatus.SCHEDULED:
        return False
    approvers = payment.approvers or []
    if not approvers:
        return True
    return all(str(a.get("state", "")) == "approved" for a in approvers)


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
            checks.recommended_action = "Add a verified payout method on the vendor record."
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

    status = method.status or "not_configured"
    if status != "verified":
        checks.blocking_reasons.append(f"Vendor payout method status is {status}, not verified")

    checks.vendor_payout_ready = (
        method is not None
        and method_type in _EXECUTION_SUPPORTED_METHOD_TYPES
        and status == "verified"
        and (method_type != "stripe_connected_account" or bool(method.stripe_account_id))
    )


async def _build_readiness_checks(
    db: AsyncSession,
    payment: Payment,
    *,
    stripe: StripeReadiness | None = None,
) -> _ReadinessChecks:
    checks = _ReadinessChecks()

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

    currency = (payment.currency or "AUD").upper()
    if currency not in _SUPPORTED_CURRENCIES:
        checks.blocking_reasons.append(f"Payment currency {currency} is not supported")
        checks.amount_ready = False
    elif checks.amount_ready and not payment.due_date:
        checks.warnings.append("Payment due date is missing; confirm scheduling before execution")

    checks.approval_ready = _approval_ready(payment)
    if not checks.approval_ready:
        if payment.status in (PaymentStatus.QUEUE, PaymentStatus.AWAITING):
            checks.blocking_reasons.append("Payment approval workflow is incomplete")
        else:
            checks.blocking_reasons.append(
                "Payment is not approved for execution (status must be scheduled with approvals complete)"
            )
        if checks.recommended_action is None:
            checks.recommended_action = "Complete tiered payment approval before validating execution."

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
            "STRIPE_PAYMENTS_EXECUTION_ENABLED is true but real execution endpoints are not implemented yet."
        )

    return checks


def _to_readiness_result(
    payment_id: int,
    checks: _ReadinessChecks,
) -> PaymentExecutionReadiness:
    settings = get_settings()
    can_execute = (
        not checks.blocking_reasons
        and checks.tenant_stripe_ready
        and checks.vendor_payout_ready
        and checks.approval_ready
        and checks.amount_ready
    )
    recommended = checks.recommended_action
    if can_execute:
        recommended = (
            "Dry-run validation passed. Real Stripe execution remains disabled until "
            "production safety flags and business signoff are complete."
        )
    return PaymentExecutionReadiness(
        payment_id=payment_id,
        can_execute=can_execute,
        execution_mode="dry_run",
        blocking_reasons=checks.blocking_reasons,
        warnings=checks.warnings,
        tenant_stripe_ready=checks.tenant_stripe_ready,
        vendor_payout_ready=checks.vendor_payout_ready,
        approval_ready=checks.approval_ready,
        amount_ready=checks.amount_ready,
        recommended_action=recommended,
        payments_execution_enabled=settings.stripe_payment_execution_enabled,
    )


async def validate_payment_execution_readiness(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    payment_id: int,
    *,
    actor: dict[str, Any] | None = None,
) -> PaymentExecutionReadiness:
    """Read-only dry-run validation; does not mutate payment or call Stripe money APIs."""
    _ = actor
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

    checks = await _build_readiness_checks(db, payment)
    return _to_readiness_result(payment.id, checks)


def derive_execution_eligibility(
    payment: Payment,
    *,
    stripe: StripeReadiness,
    vendor_payout_status: str | None,
    vendor_payout_method_type: str | None,
    has_instruction: bool = False,
    manual_execution_enabled: bool = False,
    manual_instruction_eligible: bool = False,
) -> tuple[str, str | None]:
    """Read-only eligibility label for payment list UI."""
    if payment.status == PaymentStatus.PAID:
        return "paid", None
    if payment.status == PaymentStatus.FAILED:
        return "failed", payment.failure_reason

    if payment.status in (PaymentStatus.QUEUE, PaymentStatus.AWAITING):
        return "awaiting_approval", "Complete payment approval workflow"

    stripe_ready = (
        stripe.connected
        and stripe.charges_enabled
        and stripe.payouts_enabled
        and stripe.blocking_reason is None
    )
    vendor_ready = (
        vendor_payout_status == "verified"
        and vendor_payout_method_type in _EXECUTION_SUPPORTED_METHOD_TYPES
    )

    if payment.status == PaymentStatus.SCHEDULED:
        if has_instruction:
            return "instruction_created", None

        manual_bank_verified = (
            vendor_payout_method_type == "manual_bank" and vendor_payout_status == "verified"
        )
        if manual_execution_enabled and manual_instruction_eligible:
            return "manual_instruction_available", None

        if not stripe_ready:
            reason = stripe.blocking_reason or "Stripe setup is incomplete"
            if manual_execution_enabled and manual_bank_verified:
                return "manual_instruction_available", reason
            return "blocked_stripe_setup", reason
        if not vendor_ready:
            if not vendor_payout_status or vendor_payout_status == "not_configured":
                return "blocked_vendor_payout_setup", "Vendor payout method is not configured"
            return (
                "blocked_vendor_payout_setup",
                f"Vendor payout method is {vendor_payout_status or 'not ready'}",
            )
        if _approval_ready(payment):
            if manual_execution_enabled:
                return "manual_instruction_available", None
            return "ready_dry_run", None
        return "scheduled", "Payment is scheduled but approval chain may be incomplete"

    return "not_ready", None
