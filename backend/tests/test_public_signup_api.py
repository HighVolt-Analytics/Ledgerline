"""Public self-serve signup API (no invite token)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.pending_signup_billing import PendingSignupBillingSession
from app.models.tenant import Tenant
from app.models.tenant_billing import TenantBilling
from app.services.credit_catalog import PLAN_FREE, PLAN_STUDIO
from app.services.payments.stripe_platform_billing_service import SIGNUP_STATUS_PENDING


class FakeStripeObject:
    """Minimal StripeObject stand-in for tests."""

    def __init__(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_public_signup_checkout_free_without_token(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    slug = f"public-free-{uuid.uuid4().hex[:8]}"
    email = f"{slug}@example.com"
    with patch(
        "app.services.payments.stripe_platform_billing_service._unique_slug",
        new=AsyncMock(return_value=slug),
    ):
        res = await client.post(
            "/api/billing/signup/checkout",
            json={
                "email": email,
                "password": "password123",
                "organisation_name": "Public Free Org",
                "country": "AU",
                "plan_code": "free",
                "signup_source": "public",
            },
        )
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["completed_without_checkout"] is True
    assert body["tenant_id"]
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user"]["email"] == email

    tenant = await db_session.get(Tenant, uuid.UUID(body["tenant_id"]))
    assert tenant is not None
    assert tenant.slug == slug
    billing = await db_session.get(TenantBilling, tenant.id)
    assert billing is not None
    assert billing.plan == PLAN_FREE
    assert billing.credit_balance >= 50


@pytest.mark.asyncio
async def test_public_studio_signup_with_stripe_object_checkout(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_PLATFORM_BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_PRICE_STUDIO_AUD", "price_test_studio")
    monkeypatch.setenv("STRIPE_PLATFORM_BILLING_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    get_settings.cache_clear()

    slug = f"stripe-obj-{uuid.uuid4().hex[:8]}"
    email = f"{slug}@example.com"
    mock_checkout = FakeStripeObject(
        id="cs_stripe_object_1",
        url="https://checkout.stripe.test/stripe-object",
    )

    with (
        patch(
            "app.services.payments.stripe_platform_billing_service._unique_slug",
            new=AsyncMock(return_value=slug),
        ),
        patch(
            "app.services.payments.stripe_platform_billing_service._run_stripe",
            new=AsyncMock(return_value=mock_checkout),
        ),
    ):
        res = await client.post(
            "/api/billing/signup/checkout",
            json={
                "email": email,
                "password": "password123",
                "organisation_name": "Stripe Object Org",
                "country": "AU",
                "plan_code": "studio",
                "signup_source": "public",
            },
        )

    assert res.status_code == 200
    body = res.json()["data"]
    assert body["checkout_url"] == "https://checkout.stripe.test/stripe-object"
    assert body["session_id"] == "cs_stripe_object_1"


@pytest.mark.asyncio
async def test_public_studio_signup_pending_before_webhook(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_PLATFORM_BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_PRICE_STUDIO_AUD", "price_test_studio")
    monkeypatch.setenv("STRIPE_PLATFORM_BILLING_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    get_settings.cache_clear()

    slug = f"public-studio-{uuid.uuid4().hex[:8]}"
    email = f"{slug}@example.com"

    mock_checkout = {
        "id": "cs_public_studio_1",
        "url": "https://checkout.stripe.test/session",
    }

    with (
        patch(
            "app.services.payments.stripe_platform_billing_service._unique_slug",
            new=AsyncMock(return_value=slug),
        ),
        patch(
            "app.services.payments.stripe_platform_billing_service._run_stripe",
            new=AsyncMock(return_value=mock_checkout),
        ),
    ):
        res = await client.post(
            "/api/billing/signup/checkout",
            json={
                "email": email,
                "password": "password123",
                "organisation_name": "Public Studio Org",
                "country": "AU",
                "plan_code": "studio",
                "signup_source": "public",
            },
        )

    assert res.status_code == 200
    body = res.json()["data"]
    assert body["checkout_url"]
    assert body["session_id"] == "cs_public_studio_1"
    assert body["completed_without_checkout"] is False

    tenant = (
        await db_session.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    assert tenant is None

    pending = (
        await db_session.execute(
            select(PendingSignupBillingSession).where(
                PendingSignupBillingSession.stripe_checkout_session_id == "cs_public_studio_1"
            )
        )
    ).scalar_one()
    assert pending.status == SIGNUP_STATUS_PENDING
    assert pending.plan_code == PLAN_STUDIO
    assert pending.signup_source == "public"
    assert pending.tenant_id is None


@pytest.mark.asyncio
async def test_public_signup_rejects_signup_token(client: AsyncClient) -> None:
    res = await client.post(
        "/api/billing/signup/checkout",
        json={
            "email": "token-user@example.com",
            "password": "password123",
            "organisation_name": "Should Fail",
            "country": "AU",
            "plan_code": "free",
            "signup_source": "public",
            "signup_token": "not-allowed-for-public",
        },
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_invite_preview_still_requires_valid_token(client: AsyncClient) -> None:
    res = await client.get("/api/auth/invite/preview", params={"token": "invalid-token"})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_public_studio_signup_missing_stripe_key_returns_clean_error(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIPE_PLATFORM_BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_PRICE_STUDIO_AUD", "price_test_studio")
    monkeypatch.setenv("STRIPE_PLATFORM_BILLING_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "")
    monkeypatch.setenv("STRIPE_PLATFORM_BILLING_SECRET_KEY", "")
    get_settings.cache_clear()

    slug = f"no-key-{uuid.uuid4().hex[:8]}"
    with patch(
        "app.services.payments.stripe_platform_billing_service._unique_slug",
        new=AsyncMock(return_value=slug),
    ):
        res = await client.post(
            "/api/billing/signup/checkout",
            json={
                "email": f"{slug}@example.com",
                "password": "password123",
                "organisation_name": "Missing Key Org",
                "country": "AU",
                "plan_code": "studio",
                "signup_source": "public",
            },
        )

    assert res.status_code == 503
    assert res.json()["detail"] == "Stripe platform billing is not configured"


@pytest.mark.asyncio
async def test_public_signup_link(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:5173")
    get_settings.cache_clear()

    res = await client.get("/api/signup/link")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["path"] == "/signup"
    assert body["url"] == "http://localhost:5173/signup"
    assert "/start" in body["aliases"]
    assert "Get started with Ledgerlink" in body["embed_html"]
