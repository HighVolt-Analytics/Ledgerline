"""PayPal webhook verification and payout attempt updates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.payment import Payment, PaymentStatus
from app.models.stripe_payments import PaymentAttempt
from app.models.tenant_payment_provider import (
    PROVIDER_PAYPAL,
    PaypalWebhookEvent,
    TenantPaymentProviderAccount,
)
from app.services.audit.audit_service import log_event
from app.services.payments.paypal_client import PaypalApiError, get_paypal_client
from app.services.payments.paypal_payout_service import (
    ATTEMPT_STATUS_FAILED,
    ATTEMPT_STATUS_PENDING,
    ATTEMPT_STATUS_RETURNED,
    ATTEMPT_STATUS_SUCCEEDED,
    ATTEMPT_STATUS_UNCLAIMED,
    ATTEMPT_STATUS_CANCELLED,
    is_terminal_attempt_status,
    map_paypal_item_status,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class PaypalWebhookError(Exception):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


async def verify_paypal_webhook(
    *,
    headers: dict[str, str],
    body: bytes | str,
) -> dict[str, Any]:
    """Official PayPal verify-webhook-signature flow; requires SUCCESS."""
    settings = get_settings()
    webhook_id = settings.paypal_webhook_id.strip()
    if not webhook_id:
        raise PaypalWebhookError(
            "PAYPAL_WEBHOOK_ID is not configured",
            code="webhook_not_configured",
        )
    if not settings.paypal_configured:
        raise PaypalWebhookError("PayPal is not configured", code="paypal_not_configured")

    if isinstance(body, bytes):
        raw_text = body.decode("utf-8")
    else:
        raw_text = body

    try:
        event = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise PaypalWebhookError("Invalid webhook JSON", code="invalid_json") from exc

    def _hdr(name: str) -> str:
        # Case-insensitive header lookup
        for key, value in headers.items():
            if key.lower() == name.lower():
                return str(value)
        return ""

    transmission_id = _hdr("PAYPAL-TRANSMISSION-ID")
    transmission_time = _hdr("PAYPAL-TRANSMISSION-TIME")
    transmission_sig = _hdr("PAYPAL-TRANSMISSION-SIG")
    cert_url = _hdr("PAYPAL-CERT-URL")
    auth_algo = _hdr("PAYPAL-AUTH-ALGO")

    if not all(
        [transmission_id, transmission_time, transmission_sig, cert_url, auth_algo]
    ):
        raise PaypalWebhookError(
            "Missing PayPal transmission headers",
            code="missing_headers",
        )

    client = get_paypal_client()
    try:
        result = await client.request_json(
            "POST",
            "/v1/notifications/verify-webhook-signature",
            json={
                "transmission_id": transmission_id,
                "transmission_time": transmission_time,
                "cert_url": cert_url,
                "auth_algo": auth_algo,
                "transmission_sig": transmission_sig,
                "webhook_id": webhook_id,
                "webhook_event": event,
            },
        )
    except PaypalApiError as exc:
        raise PaypalWebhookError(
            "PayPal webhook signature verification failed",
            code=exc.error_code or "verification_failed",
        ) from exc

    status = str(result.get("verification_status") or "").upper()
    if status != "SUCCESS":
        raise PaypalWebhookError(
            f"PayPal webhook verification status={status}",
            code="verification_rejected",
        )
    return event if isinstance(event, dict) else {}


def _extract_merchant_id(event: dict[str, Any]) -> str | None:
    resource = event.get("resource") or {}
    for key in (
        "merchant_id",
        "payer_id",
        "account_id",
        "seller_merchant_id",
    ):
        value = resource.get(key)
        if value:
            return str(value).strip()

    for key in ("merchant_id", "payer_id"):
        value = event.get(key)
        if value:
            return str(value).strip()

    # Some payout events nest under resource.payout_item / batch header
    for nested_key in ("payout_item", "batch_header", "transaction"):
        nested = resource.get(nested_key) or {}
        if isinstance(nested, dict):
            for key in ("merchant_id", "payer_id", "sender_batch_id"):
                value = nested.get(key)
                if value and key != "sender_batch_id":
                    return str(value).strip()
    return None


async def _resolve_account_for_merchant(
    db: AsyncSession,
    merchant_id: str,
) -> TenantPaymentProviderAccount | None:
    return (
        await db.execute(
            select(TenantPaymentProviderAccount).where(
                TenantPaymentProviderAccount.provider == PROVIDER_PAYPAL,
                TenantPaymentProviderAccount.status != "disconnected",
                or_(
                    TenantPaymentProviderAccount.provider_merchant_id == merchant_id,
                    TenantPaymentProviderAccount.provider_account_id == merchant_id,
                ),
            )
        )
    ).scalar_one_or_none()


async def persist_webhook_event(
    db: AsyncSession,
    event: dict[str, Any],
    *,
    verification_status: str = "SUCCESS",
    provider_account_id: str | None = None,
) -> tuple[PaypalWebhookEvent, bool]:
    """Persist webhook event; returns (row, is_duplicate)."""
    event_id = str(event.get("id") or "").strip()
    if not event_id:
        raise PaypalWebhookError("Webhook event missing id", code="missing_event_id")

    existing = (
        await db.execute(
            select(PaypalWebhookEvent).where(
                PaypalWebhookEvent.paypal_event_id == event_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, True

    row = PaypalWebhookEvent(
        paypal_event_id=event_id,
        event_type=str(event.get("event_type") or "unknown")[:128],
        provider_account_id=provider_account_id,
        payload_json=json.dumps(event, default=str)[:100_000],
        verification_status=verification_status,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        existing = (
            await db.execute(
                select(PaypalWebhookEvent).where(
                    PaypalWebhookEvent.paypal_event_id == event_id
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise PaypalWebhookError(
                "Unable to record PayPal webhook event",
                code="persist_failed",
            )
        return existing, True
    return row, False


async def _find_attempt_for_payout_event(
    db: AsyncSession,
    *,
    tenant_id,
    resource: dict[str, Any],
) -> PaymentAttempt | None:
    batch_id = str(
        resource.get("payout_batch_id")
        or (resource.get("batch_header") or {}).get("payout_batch_id")
        or ""
    ).strip()
    item_id = str(
        resource.get("payout_item_id")
        or (resource.get("payout_item") or {}).get("payout_item_id")
        or ""
    ).strip()
    txn_id = str(resource.get("transaction_id") or "").strip()

    if item_id:
        row = (
            await db.execute(
                select(PaymentAttempt).where(
                    PaymentAttempt.tenant_id == tenant_id,
                    PaymentAttempt.provider == PROVIDER_PAYPAL,
                    PaymentAttempt.provider_item_id == item_id,
                )
            )
        ).scalar_one_or_none()
        if row:
            return row

    if batch_id:
        row = (
            await db.execute(
                select(PaymentAttempt).where(
                    PaymentAttempt.tenant_id == tenant_id,
                    PaymentAttempt.provider == PROVIDER_PAYPAL,
                    PaymentAttempt.provider_batch_id == batch_id,
                )
            )
        ).scalar_one_or_none()
        if row:
            return row

    if txn_id:
        return (
            await db.execute(
                select(PaymentAttempt).where(
                    PaymentAttempt.tenant_id == tenant_id,
                    PaymentAttempt.provider == PROVIDER_PAYPAL,
                    PaymentAttempt.provider_transaction_id == txn_id,
                )
            )
        ).scalar_one_or_none()
    return None


async def _apply_payout_status(
    db: AsyncSession,
    attempt: PaymentAttempt,
    *,
    provider_status: str,
    resource: dict[str, Any],
) -> None:
    previous = attempt.status
    mapped = map_paypal_item_status(provider_status)
    # Narrow known webhook-friendly aliases
    upper = provider_status.upper()
    if upper in ("SUCCESS", "COMPLETED"):
        mapped = ATTEMPT_STATUS_SUCCEEDED
    elif upper in ("FAILED", "DENIED", "BLOCKED"):
        mapped = ATTEMPT_STATUS_FAILED
    elif upper in ("RETURNED", "REFUNDED", "REVERSED"):
        mapped = ATTEMPT_STATUS_RETURNED
    elif upper == "UNCLAIMED":
        mapped = ATTEMPT_STATUS_UNCLAIMED
    elif upper in ("CANCELED", "CANCELLED"):
        mapped = ATTEMPT_STATUS_CANCELLED
    elif upper in ("PENDING", "PROCESSING", "ONHOLD"):
        mapped = ATTEMPT_STATUS_PENDING

    item = resource.get("payout_item") if isinstance(resource.get("payout_item"), dict) else {}
    attempt.provider_status = provider_status
    attempt.provider_item_id = (
        str(resource.get("payout_item_id") or item.get("payout_item_id") or "").strip()
        or attempt.provider_item_id
    )
    attempt.provider_batch_id = (
        str(
            resource.get("payout_batch_id")
            or (resource.get("batch_header") or {}).get("payout_batch_id")
            or ""
        ).strip()
        or attempt.provider_batch_id
    )
    attempt.provider_transaction_id = (
        str(resource.get("transaction_id") or "").strip()
        or attempt.provider_transaction_id
    )
    attempt.status = mapped
    attempt.last_checked_at = datetime.now(timezone.utc)
    if is_terminal_attempt_status(mapped):
        attempt.completed_at = attempt.completed_at or datetime.now(timezone.utc)

    errors = resource.get("errors") or item.get("errors") or {}
    if isinstance(errors, dict) and errors:
        attempt.failure_code = str(errors.get("name") or attempt.failure_code)
        attempt.failure_message = str(
            errors.get("message") or attempt.failure_message or ""
        )[:2000]

    if mapped == ATTEMPT_STATUS_SUCCEEDED and attempt.tenant_id is not None:
        payment = await db.get(Payment, attempt.payment_id)
        if payment is not None and payment.tenant_id == attempt.tenant_id:
            payment.status = PaymentStatus.PAID
            payment.paid_date = payment.paid_date or datetime.now(timezone.utc)

    await db.flush()

    if previous != attempt.status and attempt.tenant_id is not None:
        await log_event(
            db,
            "paypal_webhook_attempt_updated",
            tenant_id=attempt.tenant_id,
            detail={
                "attempt_id": attempt.id,
                "payment_id": attempt.payment_id,
                "from_status": previous,
                "to_status": attempt.status,
                "provider_status": attempt.provider_status,
            },
        )


async def process_paypal_webhook_event(
    db: AsyncSession,
    event: dict[str, Any],
) -> dict[str, Any]:
    """
    Process a verified PayPal webhook.

    Tenant is resolved ONLY via TenantPaymentProviderAccount merchant mapping —
    never from payload tenant_id.
    """
    merchant_id = _extract_merchant_id(event)
    account = None
    if merchant_id:
        account = await _resolve_account_for_merchant(db, merchant_id)

    row, duplicate = await persist_webhook_event(
        db,
        event,
        verification_status="SUCCESS",
        provider_account_id=(
            (account.provider_account_id if account else None) or merchant_id
        ),
    )
    if duplicate and row.processed_at is not None:
        return {
            "duplicate": True,
            "processed": False,
            "event_id": row.paypal_event_id,
            "event_type": row.event_type,
        }

    event_type = str(event.get("event_type") or "")
    resource = event.get("resource") if isinstance(event.get("resource"), dict) else {}

    try:
        if account is None:
            # Still accept/persist; cannot map to tenant safely.
            row.process_error = "merchant_account_not_mapped"
            row.processed_at = datetime.now(timezone.utc)
            await db.flush()
            return {
                "duplicate": duplicate,
                "processed": False,
                "reason": "merchant_account_not_mapped",
                "event_id": row.paypal_event_id,
                "event_type": event_type,
            }

        # Never trust tenant_id from payload — use account mapping only.
        tenant_id = account.tenant_id

        if event_type.startswith("PAYMENT.PAYOUTS-ITEM.") or event_type.startswith(
            "PAYMENT.PAYOUTSBATCH."
        ):
            attempt = await _find_attempt_for_payout_event(
                db, tenant_id=tenant_id, resource=resource
            )
            if attempt is not None:
                provider_status = str(
                    resource.get("transaction_status")
                    or (resource.get("batch_header") or {}).get("batch_status")
                    or event_type.rsplit(".", 1)[-1]
                )
                await _apply_payout_status(
                    db,
                    attempt,
                    provider_status=provider_status,
                    resource=resource,
                )

        row.processed_at = datetime.now(timezone.utc)
        row.process_error = None
        await db.flush()
        return {
            "duplicate": duplicate,
            "processed": True,
            "event_id": row.paypal_event_id,
            "event_type": event_type,
            "tenant_id": str(tenant_id),
        }
    except Exception as exc:
        row.process_error = str(exc)[:512]
        await db.flush()
        logger.exception(
            "paypal_webhook_process_failed",
            event_id=row.paypal_event_id,
            event_type=event_type,
        )
        raise


async def handle_paypal_webhook(
    db: AsyncSession,
    *,
    headers: dict[str, str],
    body: bytes | str,
) -> dict[str, Any]:
    event = await verify_paypal_webhook(headers=headers, body=body)
    return await process_paypal_webhook_event(db, event)
