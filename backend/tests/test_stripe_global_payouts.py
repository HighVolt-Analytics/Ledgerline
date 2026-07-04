"""Stripe Global Payouts readiness — configuration only, no money APIs."""

import pytest

from app.config import get_settings
from app.schemas.payment import StripeGlobalPayoutsReadinessResponse
from app.services.payments.payment_rail_service import (
    PAYMENT_RAIL_MANUAL,
    PAYMENT_RAIL_STRIPE_GLOBAL_PAYOUTS,
    get_selected_payment_rail,
    validate_payment_rail_readiness,
)
from app.services.payments.stripe_global_payouts_service import (
    get_stripe_global_payouts_readiness,
    stripe_global_payouts_readiness_payload,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    defaults = {
        "STRIPE_GLOBAL_PAYOUTS_ENABLED": "false",
        "STRIPE_GLOBAL_PAYOUTS_ACCESS_STATUS": "not_requested",
        "STRIPE_GLOBAL_PAYOUTS_FINANCIAL_ACCOUNT_ID": "",
        "STRIPE_PAYMENTS_EXECUTION_ENABLED": "false",
        "STRIPE_LIVE_PAYMENTS_ENABLED": "false",
        "APP_ENV": "preview",
        "STRIPE_MODE": "test",
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def test_global_payouts_disabled_returns_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    readiness = get_stripe_global_payouts_readiness()
    assert readiness.ready is False
    assert readiness.blocking_reason == "Stripe Global Payouts access is not enabled."


def test_pending_approval_blocks_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(
        monkeypatch,
        STRIPE_GLOBAL_PAYOUTS_ENABLED="true",
        STRIPE_GLOBAL_PAYOUTS_ACCESS_STATUS="pending_approval",
    )
    readiness = get_stripe_global_payouts_readiness()
    assert readiness.ready is False
    assert readiness.blocking_reason == "Stripe Global Payouts approval is pending with Stripe."


def test_enabled_with_financial_account_is_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(
        monkeypatch,
        STRIPE_GLOBAL_PAYOUTS_ENABLED="true",
        STRIPE_GLOBAL_PAYOUTS_ACCESS_STATUS="enabled",
        STRIPE_GLOBAL_PAYOUTS_FINANCIAL_ACCOUNT_ID="fa_123",
    )
    readiness = get_stripe_global_payouts_readiness()
    assert readiness.ready is True
    assert readiness.financial_account_configured is True
    assert readiness.live_execution_enabled is False


def test_production_live_flags_false_blocks_live_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(
        monkeypatch,
        APP_ENV="production",
        STRIPE_MODE="live",
        STRIPE_GLOBAL_PAYOUTS_ENABLED="true",
        STRIPE_GLOBAL_PAYOUTS_ACCESS_STATUS="enabled",
        STRIPE_GLOBAL_PAYOUTS_FINANCIAL_ACCOUNT_ID="fa_123",
    )
    readiness = get_stripe_global_payouts_readiness()
    assert readiness.ready is True
    assert readiness.live_execution_enabled is False
    assert readiness.environment == "production"
    assert readiness.stripe_mode == "live"


def test_payment_rail_defaults_to_manual(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    assert get_selected_payment_rail() == PAYMENT_RAIL_MANUAL


def test_payment_rail_selects_global_payouts_when_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(
        monkeypatch,
        STRIPE_GLOBAL_PAYOUTS_ENABLED="true",
        STRIPE_GLOBAL_PAYOUTS_ACCESS_STATUS="enabled",
        STRIPE_GLOBAL_PAYOUTS_FINANCIAL_ACCOUNT_ID="fa_123",
    )
    settings = get_settings()
    assert get_selected_payment_rail(settings) == PAYMENT_RAIL_STRIPE_GLOBAL_PAYOUTS
    ready, _, _ = validate_payment_rail_readiness(
        PAYMENT_RAIL_STRIPE_GLOBAL_PAYOUTS,
        settings=settings,
    )
    assert ready is False


def test_readiness_payload_is_schema_compatible(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(
        monkeypatch,
        STRIPE_GLOBAL_PAYOUTS_ENABLED="true",
        STRIPE_GLOBAL_PAYOUTS_ACCESS_STATUS="enabled",
        STRIPE_GLOBAL_PAYOUTS_FINANCIAL_ACCOUNT_ID="fa_123",
    )
    readiness = get_stripe_global_payouts_readiness()
    payload = stripe_global_payouts_readiness_payload()
    response = StripeGlobalPayoutsReadinessResponse.model_validate(payload)
    assert response.ready is True
    assert response.access_status == "enabled"
    assert response.supported_countries == readiness.supported_countries
    assert response.live_execution_enabled is False
