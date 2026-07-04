"""Payment rail selection and readiness — no money movement."""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.models.payment import Payment
from app.services.payments.stripe_global_payouts_service import (
    StripeGlobalPayoutsReadiness,
    get_stripe_global_payouts_readiness,
)

PAYMENT_RAIL_MANUAL = "manual_instruction"
PAYMENT_RAIL_STRIPE_GLOBAL_PAYOUTS = "stripe_global_payouts"
PAYMENT_RAIL_STRIPE_TREASURY = "stripe_treasury"
PAYMENT_RAIL_EXTERNAL_AP = "external_ap_provider"

PAYMENT_RAILS = frozenset(
    {
        PAYMENT_RAIL_MANUAL,
        PAYMENT_RAIL_STRIPE_GLOBAL_PAYOUTS,
        PAYMENT_RAIL_STRIPE_TREASURY,
        PAYMENT_RAIL_EXTERNAL_AP,
    }
)


def get_selected_payment_rail(settings: Settings | None = None) -> str:
    s = settings or get_settings()
    readiness = get_stripe_global_payouts_readiness(s)
    if readiness.ready and s.stripe_global_payouts_enabled:
        return PAYMENT_RAIL_STRIPE_GLOBAL_PAYOUTS
    return PAYMENT_RAIL_MANUAL


def validate_payment_rail_readiness(
    rail: str,
    *,
    payment: Payment | None = None,
    global_payouts: StripeGlobalPayoutsReadiness | None = None,
    settings: Settings | None = None,
) -> tuple[bool, str | None, str | None]:
    _ = payment
    s = settings or get_settings()
    gp = global_payouts or get_stripe_global_payouts_readiness(s)

    if rail == PAYMENT_RAIL_MANUAL:
        return True, None, "Use manual payment instruction orchestration"

    if rail == PAYMENT_RAIL_STRIPE_GLOBAL_PAYOUTS:
        if not gp.ready:
            return False, gp.blocking_reason, gp.recommended_action
        if not gp.live_execution_enabled:
            return (
                False,
                "Live payout execution is disabled by server configuration.",
                "Enable live execution flags after Stripe Global Payouts go-live approval.",
            )
        return True, None, "Stripe Global Payouts rail is configured (execution APIs not enabled yet)"

    if rail in (PAYMENT_RAIL_STRIPE_TREASURY, PAYMENT_RAIL_EXTERNAL_AP):
        return (
            False,
            f"Payment rail '{rail}' is not enabled.",
            "Use manual_instruction until provider rail is implemented.",
        )

    return False, f"Unknown payment rail '{rail}'.", "Use manual_instruction"


def payment_rail_context(settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    gp = get_stripe_global_payouts_readiness(s)
    rail = get_selected_payment_rail(s)
    rail_ready, _, rail_action = validate_payment_rail_readiness(
        rail,
        global_payouts=gp,
        settings=s,
    )
    return {
        "selected_payment_rail": rail,
        "stripe_global_payouts_ready": gp.ready,
        "stripe_global_payouts_blocking_reason": gp.blocking_reason,
        "payment_rail_ready": rail_ready,
        "payment_rail_recommended_action": rail_action,
        "app_env": _resolved_app_env(s),
        "stripe_mode": s.stripe_mode_normalized,
        "live_execution_enabled": gp.live_execution_enabled,
    }


def _resolved_app_env(settings: Settings) -> str:
    env = settings.app_env.strip().lower()
    if env in ("production", "prod"):
        return "production"
    return "preview"
