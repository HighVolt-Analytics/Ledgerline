"""Shared production rules for manual payment execution orchestration."""

from __future__ import annotations

from decimal import Decimal

from app.config import get_settings
from app.models.payment import Payment, PaymentStatus
from app.models.stripe_payments import VendorPaymentMethod

LIMIT_BLOCK_MESSAGE = "Payment exceeds production manual execution limit."
VENDOR_NOT_VERIFIED_MESSAGE = "Vendor payout method is not verified."
TENANT_DISABLED_MESSAGE = "Payment execution is disabled for this tenant."


def approval_ready(payment: Payment) -> bool:
    if payment.status != PaymentStatus.SCHEDULED:
        return False
    approvers = payment.approvers or []
    if not approvers:
        return True
    return all(str(a.get("state", "")) == "approved" for a in approvers)


def vendor_payout_method_verified(method: VendorPaymentMethod | None) -> bool:
    if method is None:
        return False
    return (method.status or "") == "verified"


def check_payment_manual_execution_limit(
    payment: Payment,
) -> tuple[bool, str | None, list[str]]:
    settings = get_settings()
    limit = Decimal(str(settings.payment_manual_execution_limit_usd))
    amount = Decimal(str(payment.amount or 0))
    currency = (payment.currency or "").strip().upper()
    warnings: list[str] = []

    if amount > limit:
        return False, LIMIT_BLOCK_MESSAGE, warnings

    if not currency:
        warnings.append(
            f"Payment currency is missing; USD {limit} launch limit applied conservatively."
        )
    elif currency != "USD":
        warnings.append(
            f"No FX conversion available; USD {limit} launch limit applied conservatively "
            f"to {currency} {amount}."
        )
    return True, None, warnings


def manual_instruction_eligible(
    payment: Payment,
    *,
    approval_ready_flag: bool,
    amount_ready: bool,
    method: VendorPaymentMethod | None,
    tenant_enabled: bool = True,
) -> tuple[bool, str | None]:
    if not tenant_enabled:
        return False, TENANT_DISABLED_MESSAGE

    if payment.status != PaymentStatus.SCHEDULED:
        return False, "Payment must be scheduled before creating an instruction"

    if not approval_ready_flag:
        return False, "Approve payment first"

    if not amount_ready:
        return False, "Payment amount or currency is not valid for execution"

    limit_ok, limit_reason, _ = check_payment_manual_execution_limit(payment)
    if not limit_ok:
        return False, limit_reason

    if method is None:
        return False, VENDOR_NOT_VERIFIED_MESSAGE

    if not vendor_payout_method_verified(method):
        return False, VENDOR_NOT_VERIFIED_MESSAGE

    return True, None
