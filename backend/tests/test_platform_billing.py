"""Platform Stripe billing — plan catalogue, webhook idempotency, public signup validation."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.config import get_settings
from app.models.credit_ledger import CreditLedgerEntry
from app.models.pending_signup_billing import PendingSignupBillingSession
from app.models.tenant import Tenant
from app.models.tenant_billing import TenantBilling
from app.services.credit_catalog import (
    PLAN_FREE,
    PLAN_STUDIO,
    list_country_plans,
    pricing_region_for_country,
    region_currency,
)
from app.services.credit_service import grant_credits_idempotent
from app.services.payments.stripe_platform_billing_service import (
    SIGNUP_SOURCE_PUBLIC,
    SIGNUP_STATUS_COMPLETED,
    SIGNUP_STATUS_PENDING,
    _handle_checkout_completed,
    _handle_invoice_paid,
    _require_checkout_session_urls,
    _require_platform_stripe_secret,
    _stripe_value,
    _validate_signup_request,
)
from tests.conftest import TESTING_TENANT_UUID


def test_validate_public_signup_allows_no_token() -> None:
    _validate_signup_request(
        email="user@example.com",
        password="password123",
        organisation_name="Acme",
        country="AU",
        plan_code=PLAN_FREE,
        signup_source=SIGNUP_SOURCE_PUBLIC,
        signup_token=None,
    )


def test_validate_public_signup_rejects_token() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_signup_request(
            email="user@example.com",
            password="password123",
            organisation_name="Acme",
            country="AU",
            plan_code=PLAN_FREE,
            signup_source=SIGNUP_SOURCE_PUBLIC,
            signup_token="extra",
        )
    assert exc.value.status_code == 400


def test_require_platform_stripe_secret_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "")
    monkeypatch.setenv("STRIPE_PLATFORM_BILLING_SECRET_KEY", "")
    get_settings.cache_clear()

    with pytest.raises(HTTPException) as exc:
        _require_platform_stripe_secret()

    assert exc.value.status_code == 503
    assert exc.value.detail == "Stripe platform billing is not configured"

    get_settings.cache_clear()


def test_pricing_region_for_country_mapping() -> None:
    assert pricing_region_for_country("IN") == "IN"
    assert pricing_region_for_country("AU") == "AU"
    assert pricing_region_for_country("SG") == "SG"
    assert pricing_region_for_country("US") == "SG"
    assert region_currency("IN") == "INR"
    assert region_currency("AU") == "AUD"
    assert region_currency("SG") == "SGD"


def test_list_country_plans_india_studio() -> None:
    plans = {p["plan_code"]: p for p in list_country_plans(country_code="IN")}
    assert plans[PLAN_FREE]["monthly_credits"] == 50
    assert plans[PLAN_FREE]["max_users"] == 1
    assert plans[PLAN_STUDIO]["monthly_credits"] == 5000
    assert plans[PLAN_STUDIO]["max_users"] == 3
    assert plans[PLAN_STUDIO]["monthly_price"] == Decimal("5000")


def test_list_country_plans_australia_studio() -> None:
    plans = {p["plan_code"]: p for p in list_country_plans(country_code="AU")}
    assert plans[PLAN_STUDIO]["monthly_credits"] == 250
    assert plans[PLAN_STUDIO]["monthly_price"] == Decimal("50")


def test_list_country_plans_singapore_studio() -> None:
    plans = {p["plan_code"]: p for p in list_country_plans(country_code="SG")}
    assert plans[PLAN_STUDIO]["monthly_credits"] == 500
    assert plans[PLAN_STUDIO]["monthly_price"] == Decimal("50")


@pytest.mark.asyncio
async def test_grant_credits_idempotent_once(db_session) -> None:
    first = await grant_credits_idempotent(
        db_session,
        TESTING_TENANT_UUID,
        credits=25,
        idempotency_key="topup:cs_test_123",
        event_type="top_up",
        description="Test top-up",
    )
    second = await grant_credits_idempotent(
        db_session,
        TESTING_TENANT_UUID,
        credits=25,
        idempotency_key="topup:cs_test_123",
        event_type="top_up",
        description="Test top-up",
    )
    assert first is not None
    assert second is not None
    assert first.id == second.id

    rows = (
        await db_session.execute(
            select(CreditLedgerEntry).where(
                CreditLedgerEntry.tenant_id == TESTING_TENANT_UUID,
                CreditLedgerEntry.idempotency_key == "topup:cs_test_123",
            )
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_checkout_completed_topup_grants_once(db_session, monkeypatch) -> None:
    billing = await db_session.get(TenantBilling, TESTING_TENANT_UUID)
    assert billing is not None
    before = billing.credit_balance

    event = {
        "data": {
            "object": {
                "id": "cs_topup_1",
                "mode": "payment",
                "payment_status": "paid",
                "payment_intent": "pi_123",
                "metadata": {
                    "tenant_id": str(TESTING_TENANT_UUID),
                    "event_type": "credit_topup",
                    "amount": "10",
                    "currency": "SGD",
                    "credits_to_add": "100",
                },
            }
        }
    }

    with patch(
        "app.services.payments.stripe_platform_billing_service.apply_rls_session_context",
        new=AsyncMock(),
    ):
        await _handle_checkout_completed(db_session, event)
        await _handle_checkout_completed(db_session, event)

    await db_session.refresh(billing)
    assert billing.credit_balance == before + 100


@pytest.mark.asyncio
async def test_invoice_paid_skips_subscription_create(db_session, monkeypatch) -> None:
    billing = await db_session.get(TenantBilling, TESTING_TENANT_UUID)
    assert billing is not None
    billing.stripe_subscription_id = "sub_test_1"
    billing.monthly_credits = 250
    billing.plan = PLAN_STUDIO
    before = billing.credit_balance
    await db_session.flush()

    event = {
        "data": {
            "object": {
                "id": "in_create_1",
                "subscription": "sub_test_1",
                "billing_reason": "subscription_create",
                "amount_paid": 5000,
                "currency": "aud",
            }
        }
    }

    with patch(
        "app.services.payments.stripe_platform_billing_service.apply_rls_session_context",
        new=AsyncMock(),
    ):
        await _handle_invoice_paid(db_session, event)

    await db_session.refresh(billing)
    assert billing.credit_balance == before


@pytest.mark.asyncio
async def test_invoice_paid_grants_monthly_credits_once(db_session, monkeypatch) -> None:
    billing = await db_session.get(TenantBilling, TESTING_TENANT_UUID)
    assert billing is not None
    billing.stripe_subscription_id = "sub_test_2"
    billing.monthly_credits = 250
    billing.plan = PLAN_STUDIO
    before = billing.credit_balance
    await db_session.flush()

    event = {
        "data": {
            "object": {
                "id": "in_cycle_1",
                "subscription": "sub_test_2",
                "billing_reason": "subscription_cycle",
                "amount_paid": 5000,
                "currency": "aud",
                "period_start": 1_700_000_000,
                "period_end": 1_702_592_000,
            }
        }
    }

    with patch(
        "app.services.payments.stripe_platform_billing_service.apply_rls_session_context",
        new=AsyncMock(),
    ):
        await _handle_invoice_paid(db_session, event)
        await _handle_invoice_paid(db_session, event)

    await db_session.refresh(billing)
    assert billing.credit_balance == before + 250

    rows = (
        await db_session.execute(
            select(CreditLedgerEntry).where(
                CreditLedgerEntry.idempotency_key == "monthly_credits:in_cycle_1"
            )
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_studio_signup_pending_not_completed_before_webhook(db_session) -> None:
    pending = PendingSignupBillingSession(
        id=uuid.uuid4(),
        signup_token="tok_test",
        email="studio@example.com",
        organisation_name="Studio Co",
        organisation_slug="studio-co",
        country="AU",
        plan_code=PLAN_STUDIO,
        currency="AUD",
        monthly_credits=250,
        user_limit=3,
        status=SIGNUP_STATUS_PENDING,
        stripe_checkout_session_id="cs_signup_pending",
    )
    db_session.add(pending)
    await db_session.flush()

    tenant_count = (
        await db_session.execute(select(Tenant).where(Tenant.slug == "studio-co"))
    ).scalar_one_or_none()
    assert tenant_count is None
    assert pending.status == SIGNUP_STATUS_PENDING


@pytest.mark.asyncio
async def test_free_signup_creates_tenant_without_stripe(db_session, monkeypatch) -> None:
    monkeypatch.setenv("STRIPE_PLATFORM_BILLING_ENABLED", "false")
    from app.config import get_settings

    get_settings.cache_clear()

    from app.services.payments.stripe_platform_billing_service import complete_free_signup

    slug = f"free-signup-{uuid.uuid4().hex[:8]}"
    with patch(
        "app.services.payments.stripe_platform_billing_service._unique_slug",
        new=AsyncMock(return_value=slug),
    ):
        result = await complete_free_signup(
            db_session,
            email=f"{slug}@example.com",
            password="password123",
            organisation_name="Free Signup Org",
            country="AU",
        )

    tenant = await db_session.get(Tenant, result.tenant_id)
    assert tenant is not None
    assert tenant.slug == slug
    billing = await db_session.get(TenantBilling, tenant.id)
    assert billing is not None
    assert billing.plan == PLAN_FREE

    pending = (
        await db_session.execute(
            select(PendingSignupBillingSession).where(
                PendingSignupBillingSession.signup_token == result.signup_token
            )
        )
    ).scalar_one()
    assert pending.status == SIGNUP_STATUS_COMPLETED
    assert pending.tenant_id == tenant.id

    get_settings.cache_clear()


class _FakeStripeSession:
    def __init__(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_stripe_value_reads_dict_and_stripe_object() -> None:
    assert _stripe_value({"id": "cs_dict"}, "id") == "cs_dict"
    assert _stripe_value(_FakeStripeSession(id="cs_obj", url="https://stripe.test"), "url") == "https://stripe.test"
    assert _stripe_value(None, "id", "fallback") == "fallback"


def test_require_checkout_session_urls_accepts_stripe_object() -> None:
    checkout_url, session_id = _require_checkout_session_urls(
        _FakeStripeSession(id="cs_test", url="https://checkout.stripe.test/session")
    )
    assert checkout_url == "https://checkout.stripe.test/session"
    assert session_id == "cs_test"


def test_require_checkout_session_urls_rejects_missing_url() -> None:
    with pytest.raises(HTTPException) as exc:
        _require_checkout_session_urls(_FakeStripeSession(id="cs_test"))
    assert exc.value.status_code == 502
    assert "checkout URL" in exc.value.detail
