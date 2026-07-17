"""PayPal Standard Payouts for approved tenant payments."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.payment import Payment, PaymentStatus
from app.models.stripe_payments import PaymentAttempt, VendorPaymentMethod
from app.models.tenant_payment_provider import PROVIDER_PAYPAL
from app.services.audit.audit_service import log_event
from app.services.payments.payment_execution_rules import approval_ready
from app.services.payments.paypal_account_service import get_paypal_account_for_tenant
from app.services.payments.paypal_client import PaypalApiError, get_paypal_client
from app.utils.logger import get_logger

logger = get_logger(__name__)

PAYPAL_RECIPIENT_TYPES = frozenset({"EMAIL", "PHONE", "PAYPAL_ID"})

ATTEMPT_STATUS_CREATED = "created"
ATTEMPT_STATUS_SUBMITTED = "submitted"
ATTEMPT_STATUS_PENDING = "pending"
ATTEMPT_STATUS_SUCCEEDED = "succeeded"
ATTEMPT_STATUS_FAILED = "failed"
ATTEMPT_STATUS_RETURNED = "returned"
ATTEMPT_STATUS_UNCLAIMED = "unclaimed"
ATTEMPT_STATUS_CANCELLED = "cancelled"

TERMINAL_STATUSES = frozenset(
    {
        ATTEMPT_STATUS_SUCCEEDED,
        ATTEMPT_STATUS_FAILED,
        ATTEMPT_STATUS_RETURNED,
        ATTEMPT_STATUS_UNCLAIMED,
        ATTEMPT_STATUS_CANCELLED,
    }
)

# PayPal item transaction_status → local status
_ITEM_STATUS_MAP = {
    "SUCCESS": ATTEMPT_STATUS_SUCCEEDED,
    "FAILED": ATTEMPT_STATUS_FAILED,
    "RETURNED": ATTEMPT_STATUS_RETURNED,
    "UNCLAIMED": ATTEMPT_STATUS_UNCLAIMED,
    "REFUNDED": ATTEMPT_STATUS_RETURNED,
    "REVERSED": ATTEMPT_STATUS_RETURNED,
    "BLOCKED": ATTEMPT_STATUS_FAILED,
    "DENIED": ATTEMPT_STATUS_FAILED,
    "CANCELED": ATTEMPT_STATUS_CANCELLED,
    "CANCELLED": ATTEMPT_STATUS_CANCELLED,
    "PENDING": ATTEMPT_STATUS_PENDING,
    "ONHOLD": ATTEMPT_STATUS_PENDING,
    "NEW": ATTEMPT_STATUS_SUBMITTED,
}


class PaypalPayoutError(Exception):
    """Safe application error for PayPal payout operations."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


def build_paypal_request_id(
    *,
    tenant_id: uuid.UUID,
    payment_id: int,
    amount: Decimal,
    recipient_type: str,
    recipient_value: str,
) -> str:
    """Deterministic PayPal-Request-Id from tenant+payment+amount+recipient."""
    material = "|".join(
        [
            str(tenant_id),
            str(payment_id),
            f"{amount:.2f}",
            recipient_type.upper(),
            recipient_value.strip().lower(),
        ]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"pp-payout-{digest[:48]}"


def map_paypal_item_status(provider_status: str | None) -> str:
    key = (provider_status or "").strip().upper()
    return _ITEM_STATUS_MAP.get(key, ATTEMPT_STATUS_PENDING)


def is_terminal_attempt_status(status: str | None) -> bool:
    return (status or "") in TERMINAL_STATUSES


async def _active_attempt_for_payment(
    db: AsyncSession,
    payment_id: int,
) -> PaymentAttempt | None:
    """Provider-neutral duplicate guard: any non-failed attempt blocks a new payout."""
    rows = (
        await db.execute(
            select(PaymentAttempt).where(PaymentAttempt.payment_id == payment_id)
        )
    ).scalars().all()
    for row in rows:
        if (row.status or "") != ATTEMPT_STATUS_FAILED:
            return row
    return None


async def create_paypal_payout(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    payment_id: int,
    recipient_method_id: int,
    amount: Decimal | str | float | None = None,
    currency: str | None = None,
    note: str | None = None,
    actor_user_id: int | None = None,
) -> PaymentAttempt:
    settings = get_settings()
    if not settings.paypal_configured:
        raise PaypalPayoutError("PayPal is not configured", code="paypal_not_configured")
    if not settings.paypal_payouts_enabled:
        raise PaypalPayoutError(
            "PayPal payouts are not enabled",
            code="capability_required",
        )

    payment = await db.get(Payment, payment_id)
    if payment is None or payment.tenant_id != tenant_id:
        raise PaypalPayoutError("Payment not found", code="payment_not_found")
    if payment.status == PaymentStatus.PAID:
        raise PaypalPayoutError(
            "Payment already paid",
            code="payment_already_paid",
        )
    if not approval_ready(payment):
        raise PaypalPayoutError(
            "Payment is not approved for execution",
            code="payment_not_approved",
        )

    account = await get_paypal_account_for_tenant(db, tenant_id)
    if account is None or account.status != "connected":
        raise PaypalPayoutError(
            "PayPal account is not connected",
            code="paypal_not_connected",
        )
    if not account.payouts_enabled:
        raise PaypalPayoutError(
            "PayPal payouts are not enabled for this account",
            code="capability_required",
        )

    method = await db.get(VendorPaymentMethod, recipient_method_id)
    if (
        method is None
        or method.tenant_id != tenant_id
        or (
            payment.vendor_registry_id is not None
            and method.vendor_id != payment.vendor_registry_id
        )
    ):
        raise PaypalPayoutError(
            "Recipient method not found for this payment",
            code="recipient_not_found",
        )

    provider = (method.provider or method.method_type or "").strip().lower()
    if provider != PROVIDER_PAYPAL and method.method_type != "paypal":
        raise PaypalPayoutError(
            "Recipient method is not a PayPal method",
            code="invalid_recipient",
        )

    recipient_type = (method.recipient_type or "").strip().upper()
    recipient_value = (method.recipient_value or "").strip()
    if recipient_type not in PAYPAL_RECIPIENT_TYPES:
        raise PaypalPayoutError(
            "recipient_type must be EMAIL, PHONE, or PAYPAL_ID",
            code="invalid_recipient_type",
        )
    if not recipient_value:
        raise PaypalPayoutError(
            "recipient_value is required",
            code="invalid_recipient_value",
        )

    payout_amount = Decimal(str(amount if amount is not None else payment.amount))
    try:
        if payout_amount <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError) as exc:
        raise PaypalPayoutError("Invalid payout amount", code="invalid_amount") from exc

    payout_currency = (currency or method.currency or payment.currency or "AUD").upper()[
        :3
    ]
    payment_currency = (payment.currency or "AUD").upper()[:3]
    if payout_currency != payment_currency:
        raise PaypalPayoutError(
            "Payout currency must match payment currency",
            code="currency_mismatch",
        )
    if abs(payout_amount - Decimal(str(payment.amount))) > Decimal("0.001"):
        raise PaypalPayoutError(
            "Payout amount must match the approved payment amount",
            code="amount_mismatch",
        )

    max_amount = Decimal(str(settings.paypal_max_payout_amount))
    if payout_amount > max_amount:
        raise PaypalPayoutError(
            f"Payout exceeds configured maximum of {max_amount}",
            code="amount_limit_exceeded",
        )

    existing = await _active_attempt_for_payment(db, payment.id)
    if existing is not None:
        raise PaypalPayoutError(
            "An active payment attempt already exists for this payment",
            code="duplicate_attempt",
        )

    request_id = build_paypal_request_id(
        tenant_id=tenant_id,
        payment_id=payment.id,
        amount=payout_amount,
        recipient_type=recipient_type,
        recipient_value=recipient_value,
    )

    # Create local attempt BEFORE contacting PayPal.
    attempt = PaymentAttempt(
        tenant_id=tenant_id,
        payment_id=payment.id,
        provider=PROVIDER_PAYPAL,
        provider_request_id=request_id,
        provider_status=ATTEMPT_STATUS_CREATED,
        recipient_type=recipient_type,
        recipient_value=recipient_value,
        amount=payout_amount,
        currency=payout_currency,
        status=ATTEMPT_STATUS_CREATED,
        raw_json={"note": (note or "").strip() or None},
    )
    db.add(attempt)
    await db.flush()

    sender_batch_id = f"ll-{tenant_id.hex[:8]}-{payment.id}-{attempt.id}"
    body = {
        "sender_batch_header": {
            "sender_batch_id": sender_batch_id,
            "email_subject": "You have a payout",
            "email_message": (note or f"Payment {payment.id}").strip()[:1000],
        },
        "items": [
            {
                "recipient_type": recipient_type,
                "amount": {
                    "value": f"{payout_amount:.2f}",
                    "currency": payout_currency,
                },
                "note": (note or f"Payment {payment.id}")[:4000],
                "sender_item_id": f"payment-{payment.id}-attempt-{attempt.id}",
                "receiver": recipient_value,
            }
        ],
    }

    client = get_paypal_client()
    try:
        payload = await client.request_json(
            "POST",
            "/v1/payments/payouts",
            json=body,
            paypal_request_id=request_id,
            expected_statuses=frozenset({200, 201, 202}),
        )
    except PaypalApiError as exc:
        attempt.status = ATTEMPT_STATUS_FAILED
        attempt.provider_status = exc.error_code or "api_error"
        attempt.failure_code = exc.error_code or "paypal_api_error"
        attempt.failure_message = str(exc)[:2000]
        attempt.completed_at = datetime.now(timezone.utc)
        attempt.raw_json = {
            **(attempt.raw_json or {}),
            "error": {"code": exc.error_code, "status_code": exc.status_code},
        }
        await db.flush()
        await log_event(
            db,
            "paypal_payout_failed",
            tenant_id=tenant_id,
            detail={
                "payment_id": payment.id,
                "attempt_id": attempt.id,
                "failure_code": attempt.failure_code,
                "actor_user_id": actor_user_id,
            },
        )
        raise PaypalPayoutError(str(exc), code=exc.error_code) from exc

    batch_header = payload.get("batch_header") or {}
    batch_id = str(batch_header.get("payout_batch_id") or "").strip() or None
    batch_status = str(batch_header.get("batch_status") or "").strip() or None

    now = datetime.now(timezone.utc)
    attempt.provider_batch_id = batch_id
    attempt.provider_status = batch_status or ATTEMPT_STATUS_SUBMITTED
    # HTTP accept must NOT mark succeeded — stay submitted/pending.
    attempt.status = ATTEMPT_STATUS_SUBMITTED
    if (batch_status or "").upper() in ("PENDING", "PROCESSING"):
        attempt.status = ATTEMPT_STATUS_PENDING
    attempt.submitted_at = now
    attempt.last_checked_at = now
    attempt.raw_json = {
        **(attempt.raw_json or {}),
        "payout_create": {
            "batch_status": batch_status,
            "payout_batch_id": batch_id,
            "links": payload.get("links"),
        },
    }
    await db.flush()

    await log_event(
        db,
        "paypal_payout_submitted",
        tenant_id=tenant_id,
        detail={
            "payment_id": payment.id,
            "attempt_id": attempt.id,
            "provider_batch_id": batch_id,
            "status": attempt.status,
            "actor_user_id": actor_user_id,
        },
    )
    return attempt


async def refresh_payout_attempt(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    attempt_id: int,
) -> PaymentAttempt:
    """Reconcile a PayPal payout attempt from batch/item status."""
    attempt = await db.get(PaymentAttempt, attempt_id)
    if (
        attempt is None
        or attempt.tenant_id != tenant_id
        or (attempt.provider or "") != PROVIDER_PAYPAL
    ):
        raise PaypalPayoutError("Payment attempt not found", code="attempt_not_found")

    if is_terminal_attempt_status(attempt.status):
        attempt.last_checked_at = datetime.now(timezone.utc)
        await db.flush()
        return attempt

    if not attempt.provider_batch_id and not attempt.provider_item_id:
        raise PaypalPayoutError(
            "Attempt has no PayPal batch/item reference",
            code="missing_provider_ref",
        )

    client = get_paypal_client()
    previous_status = attempt.status

    try:
        if attempt.provider_item_id:
            payload = await client.request_json(
                "GET",
                f"/v1/payments/payouts-item/{attempt.provider_item_id}",
            )
            provider_status = str(payload.get("transaction_status") or "")
            attempt.provider_transaction_id = (
                str(payload.get("transaction_id") or "").strip() or attempt.provider_transaction_id
            )
            errors = payload.get("errors") or {}
            if isinstance(errors, dict) and errors:
                attempt.failure_code = str(errors.get("name") or attempt.failure_code)
                attempt.failure_message = str(
                    errors.get("message") or attempt.failure_message or ""
                )[:2000]
        else:
            payload = await client.request_json(
                "GET",
                f"/v1/payments/payouts/{attempt.provider_batch_id}",
            )
            batch_header = payload.get("batch_header") or {}
            items = payload.get("items") or []
            item = items[0] if items else {}
            if isinstance(item, dict):
                attempt.provider_item_id = (
                    str(item.get("payout_item_id") or "").strip() or attempt.provider_item_id
                )
                attempt.provider_transaction_id = (
                    str(item.get("transaction_id") or "").strip()
                    or attempt.provider_transaction_id
                )
                provider_status = str(
                    item.get("transaction_status")
                    or batch_header.get("batch_status")
                    or ""
                )
                errors = item.get("errors") or {}
                if isinstance(errors, dict) and errors:
                    attempt.failure_code = str(errors.get("name") or attempt.failure_code)
                    attempt.failure_message = str(
                        errors.get("message") or attempt.failure_message or ""
                    )[:2000]
            else:
                provider_status = str(batch_header.get("batch_status") or "")
    except PaypalApiError as exc:
        attempt.last_checked_at = datetime.now(timezone.utc)
        await db.flush()
        raise PaypalPayoutError(str(exc), code=exc.error_code) from exc

    mapped = map_paypal_item_status(provider_status)
    attempt.provider_status = provider_status or attempt.provider_status
    attempt.status = mapped
    attempt.last_checked_at = datetime.now(timezone.utc)
    if is_terminal_attempt_status(mapped):
        attempt.completed_at = attempt.completed_at or datetime.now(timezone.utc)

    if mapped == ATTEMPT_STATUS_SUCCEEDED:
        payment = await db.get(Payment, attempt.payment_id)
        if payment is not None and payment.tenant_id == tenant_id:
            payment.status = PaymentStatus.PAID
            payment.paid_date = payment.paid_date or datetime.now(timezone.utc)

    await db.flush()

    if previous_status != attempt.status:
        await log_event(
            db,
            "paypal_payout_status_updated",
            tenant_id=tenant_id,
            detail={
                "attempt_id": attempt.id,
                "payment_id": attempt.payment_id,
                "from_status": previous_status,
                "to_status": attempt.status,
                "provider_status": attempt.provider_status,
                "provider_batch_id": attempt.provider_batch_id,
                "provider_item_id": attempt.provider_item_id,
            },
        )
    return attempt


async def get_payout_status(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    attempt_id: int,
) -> dict[str, Any]:
    attempt = await refresh_payout_attempt(
        db, tenant_id=tenant_id, attempt_id=attempt_id
    )
    return {
        "attempt_id": attempt.id,
        "payment_id": attempt.payment_id,
        "provider": attempt.provider,
        "status": attempt.status,
        "provider_status": attempt.provider_status,
        "provider_batch_id": attempt.provider_batch_id,
        "provider_item_id": attempt.provider_item_id,
        "provider_transaction_id": attempt.provider_transaction_id,
        "provider_request_id": attempt.provider_request_id,
        "recipient_type": attempt.recipient_type,
        "recipient_value": attempt.recipient_value,
        "amount": float(attempt.amount) if attempt.amount is not None else None,
        "currency": attempt.currency,
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
        "last_checked_at": attempt.last_checked_at.isoformat()
        if attempt.last_checked_at
        else None,
        "failure_code": attempt.failure_code,
        "failure_message": attempt.failure_message,
        "terminal": is_terminal_attempt_status(attempt.status),
    }
