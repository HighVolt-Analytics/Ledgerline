"""Stripe Global Payouts readiness — configuration only; no outbound payment API calls."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import stripe
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.services.stripe_service import StripeServiceError, record_webhook_event_once
from app.utils.logger import get_logger

logger = get_logger(__name__)

GLOBAL_PAYOUTS_ACCESS_STATUSES = frozenset(
    {"not_requested", "pending_approval", "enabled", "rejected"}
)

_EXPECTED_EVENT_TYPES = frozenset(
    {
        "v2.money_management.outbound_payment.created",
        "v2.money_management.outbound_payment.posted",
        "v2.money_management.outbound_payment.failed",
        "v2.money_management.outbound_payment.returned",
        "v2.money_management.payout_method.created",
    }
)


@dataclass(frozen=True)
class StripeGlobalPayoutsReadiness:
    enabled: bool
    access_status: str
    financial_account_configured: bool
    supported_countries: list[str]
    supported_currencies: list[str]
    max_amount_usd: float
    ready: bool
    blocking_reason: str | None
    recommended_action: str | None
    environment: str
    stripe_mode: str
    live_execution_enabled: bool


def _parse_csv_list(value: str) -> list[str]:
    return [part.strip().upper() for part in value.split(",") if part.strip()]


def _resolved_environment(settings: Settings) -> str:
    env = settings.app_env.strip().lower()
    if env in ("production", "prod"):
        return "production"
    return "preview"


def _global_payouts_blocking_reason(settings: Settings) -> tuple[bool, str | None, str | None]:
    if not settings.stripe_global_payouts_enabled:
        return (
            False,
            "Stripe Global Payouts access is not enabled.",
            "Request Stripe Global Payouts access for Australia/AUD supplier AP payments.",
        )
    status = settings.stripe_global_payouts_access_status.strip().lower()
    if status == "not_requested":
        return (
            False,
            "Stripe Global Payouts access is not enabled.",
            "Request Stripe Global Payouts approval from Stripe.",
        )
    if status == "pending_approval":
        return (
            False,
            "Stripe Global Payouts approval is pending with Stripe.",
            "Wait for Stripe to enable Global Payouts on the platform account.",
        )
    if status == "rejected":
        return (
            False,
            "Stripe Global Payouts access was rejected.",
            "Contact Stripe support or use manual payment instructions.",
        )
    if status != "enabled":
        return (
            False,
            "Stripe Global Payouts access is not enabled.",
            "Set STRIPE_GLOBAL_PAYOUTS_ACCESS_STATUS=enabled after Stripe approval.",
        )
    if not settings.stripe_global_payouts_financial_account_id.strip():
        return (
            False,
            "Stripe Financial Account is not configured.",
            "Set STRIPE_GLOBAL_PAYOUTS_FINANCIAL_ACCOUNT_ID after Stripe onboarding.",
        )
    return True, None, None


def get_stripe_global_payouts_readiness(
    settings: Settings | None = None,
) -> StripeGlobalPayoutsReadiness:
    s = settings or get_settings()
    configured, blocking_reason, recommended_action = _global_payouts_blocking_reason(s)
    financial_configured = bool(s.stripe_global_payouts_financial_account_id.strip())
    ready = configured and financial_configured
    live_execution = (
        s.stripe_payment_execution_enabled
        and s.stripe_live_payments_enabled
        and ready
    )
    if ready and not live_execution:
        if not s.stripe_payment_execution_enabled or not s.stripe_live_payments_enabled:
            blocking_reason = blocking_reason or "Live payout execution is disabled by server configuration."
            recommended_action = (
                recommended_action
                or "Enable STRIPE_PAYMENTS_EXECUTION_ENABLED and STRIPE_LIVE_PAYMENTS_ENABLED after go-live approval."
            )
    return StripeGlobalPayoutsReadiness(
        enabled=bool(s.stripe_global_payouts_enabled),
        access_status=s.stripe_global_payouts_access_status.strip().lower() or "not_requested",
        financial_account_configured=financial_configured,
        supported_countries=_parse_csv_list(s.stripe_global_payouts_supported_countries),
        supported_currencies=_parse_csv_list(s.stripe_global_payouts_supported_currencies),
        max_amount_usd=float(s.stripe_global_payouts_max_amount_usd),
        ready=ready,
        blocking_reason=None if ready else blocking_reason,
        recommended_action=recommended_action,
        environment=_resolved_environment(s),
        stripe_mode=s.stripe_mode_normalized,
        live_execution_enabled=live_execution,
    )


def verify_global_payouts_webhook(payload: bytes, signature: str) -> dict[str, Any]:
    settings = get_settings()
    secret = settings.stripe_global_payouts_webhook_secret.strip()
    if not secret:
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StripeServiceError("Invalid webhook payload") from exc
        if not isinstance(parsed, dict):
            raise StripeServiceError("Invalid webhook payload")
        return parsed
    try:
        event = stripe.Webhook.construct_event(payload, signature, secret)
    except stripe.error.SignatureVerificationError as exc:
        raise StripeServiceError("Invalid webhook signature") from exc
    except ValueError as exc:
        raise StripeServiceError("Invalid webhook payload") from exc
    if hasattr(event, "to_dict"):
        return event.to_dict()
    return dict(event)


async def process_global_payouts_webhook_event(
    db: AsyncSession,
    event: dict[str, Any],
) -> None:
    event_type = str(event.get("type") or "")
    event_id = str(event.get("id") or "")
    if event_type and event_type not in _EXPECTED_EVENT_TYPES:
        logger.info(
            "stripe_global_payouts_webhook_unhandled_type",
            event_type=event_type,
            stripe_event_id=event_id or None,
        )
    if not event_id:
        logger.warning("stripe_global_payouts_webhook_missing_id", event_type=event_type or None)
        return

    class _WebhookEvent:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.id = str(payload.get("id") or "")
            self.type = str(payload.get("type") or "")
            self._payload = payload

        def to_dict(self) -> dict[str, Any]:
            return self._payload

    try:
        await record_webhook_event_once(db, _WebhookEvent(event))
    except StripeServiceError as exc:
        logger.warning(
            "stripe_global_payouts_webhook_record_failed",
            stripe_event_id=event_id,
            error=str(exc),
        )
