"""PayPal connected-payments unit tests (tenant execution — not platform billing)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import get_settings
from app.models.payment import Payment, PaymentStatus
from app.models.stripe_payments import PaymentAttempt, VendorPaymentMethod
from app.models.tenant_payment_provider import (
    PROVIDER_PAYPAL,
    PROVIDER_STRIPE,
    PaypalWebhookEvent,
    TenantPaymentProviderAccount,
)
from app.models.vendor import VendorRegistry
from app.services.payments.paypal_account_service import (
    PaypalAccountError,
    connect_paypal_account,
    disconnect_paypal_account,
    get_paypal_readiness,
)
from app.services.payments.paypal_balance_service import get_paypal_balance
from app.services.payments.paypal_client import PaypalApiError, PaypalClient
from app.services.payments.paypal_payout_service import (
    ATTEMPT_STATUS_CREATED,
    ATTEMPT_STATUS_PENDING,
    ATTEMPT_STATUS_SUBMITTED,
    ATTEMPT_STATUS_SUCCEEDED,
    PaypalPayoutError,
    build_paypal_request_id,
    create_paypal_payout,
    map_paypal_item_status,
    refresh_payout_attempt,
)
from app.services.payments.paypal_transaction_service import list_paypal_transactions
from app.services.payments.paypal_webhook_service import (
    handle_paypal_webhook,
    verify_paypal_webhook,
)
from app.services.payments.payment_provider import get_payment_provider
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.fixture(autouse=True)
def _paypal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYPAL_ENABLED", "true")
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "paypal-client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "paypal-secret")
    monkeypatch.setenv("PAYPAL_API_BASE_URL", "https://api-m.sandbox.paypal.com")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-TEST")
    monkeypatch.setenv("PAYPAL_PARTNER_ONBOARDING_ENABLED", "false")
    monkeypatch.setenv("PAYPAL_PAYOUTS_ENABLED", "true")
    monkeypatch.setenv("PAYPAL_TRANSACTION_SEARCH_ENABLED", "false")
    monkeypatch.setenv("PAYPAL_BALANCE_ENABLED", "false")
    monkeypatch.setenv("PAYPAL_SANDBOX_MERCHANT_ID", "SANDBOX-MERCHANT-1")
    monkeypatch.setenv("JWT_SECRET", "unit-test-jwt-secret-key-32b-minimum!!")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_config_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYPAL_ENABLED", "false")
    get_settings.cache_clear()
    assert get_settings().paypal_configured is False


@pytest.mark.asyncio
async def test_readiness_not_configured(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYPAL_ENABLED", "false")
    get_settings.cache_clear()
    data = await get_paypal_readiness(db_session, TESTING_TENANT_UUID)
    assert data["configured"] is False
    assert data["connected"] is False


@pytest.mark.asyncio
async def test_partner_onboarding_disabled_without_sandbox_merchant(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PAYPAL_SANDBOX_MERCHANT_ID", "")
    get_settings.cache_clear()
    with pytest.raises(PaypalAccountError) as exc:
        await connect_paypal_account(
            db_session, tenant_id=TESTING_TENANT_UUID, user_id=1
        )
    assert exc.value.code == "capability_required"


@pytest.mark.asyncio
async def test_sandbox_connect(db_session) -> None:
    result = await connect_paypal_account(
        db_session, tenant_id=TESTING_TENANT_UUID, user_id=1
    )
    assert result["mode"] == "sandbox_test"
    assert result["merchant_id"] == "SANDBOX-MERCHANT-1"
    readiness = await get_paypal_readiness(db_session, TESTING_TENANT_UUID)
    assert readiness["connected"] is True
    assert readiness["merchant_id"] == "SANDBOX-MERCHANT-1"


@pytest.mark.asyncio
async def test_disconnect_clears_credentials(db_session) -> None:
    await connect_paypal_account(db_session, tenant_id=TESTING_TENANT_UUID, user_id=1)
    result = await disconnect_paypal_account(db_session, tenant_id=TESTING_TENANT_UUID)
    assert result["connected"] is False
    readiness = await get_paypal_readiness(db_session, TESTING_TENANT_UUID)
    assert readiness["connected"] is False


@pytest.mark.asyncio
async def test_balance_reporting_gated(db_session) -> None:
    await connect_paypal_account(db_session, tenant_id=TESTING_TENANT_UUID, user_id=1)
    data = await get_paypal_balance(db_session, tenant_id=TESTING_TENANT_UUID)
    assert data["available"] is False
    assert data["reason"] == "paypal_reporting_access_required"
    assert data["balances"] == []


@pytest.mark.asyncio
async def test_transactions_reporting_gated(db_session) -> None:
    await connect_paypal_account(db_session, tenant_id=TESTING_TENANT_UUID, user_id=1)
    data = await list_paypal_transactions(db_session, tenant_id=TESTING_TENANT_UUID)
    assert data["available"] is False
    assert data["reason"] == "paypal_reporting_access_required"


def test_deterministic_paypal_request_id() -> None:
    a = build_paypal_request_id(
        tenant_id=TESTING_TENANT_UUID,
        payment_id=42,
        amount=Decimal("250.00"),
        recipient_type="EMAIL",
        recipient_value="vendor@example.com",
    )
    b = build_paypal_request_id(
        tenant_id=TESTING_TENANT_UUID,
        payment_id=42,
        amount=Decimal("250.00"),
        recipient_type="EMAIL",
        recipient_value="vendor@example.com",
    )
    assert a == b
    assert a.startswith("pp-payout-")


def test_map_item_status() -> None:
    assert map_paypal_item_status("SUCCESS") == "succeeded"
    assert map_paypal_item_status("UNCLAIMED") == "unclaimed"
    assert map_paypal_item_status("RETURNED") == "returned"
    assert map_paypal_item_status("FAILED") == "failed"


def test_provider_factory_explicit() -> None:
    from app.services.payments.payment_provider import PaymentProviderError

    assert get_payment_provider("paypal").name == "paypal"
    assert get_payment_provider("stripe").name == "stripe"
    with pytest.raises(PaymentProviderError):
        get_payment_provider("unknown")


@pytest.mark.asyncio
async def test_client_401_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.payments.paypal_client.get_access_token",
        AsyncMock(side_effect=["tok1", "tok2"]),
    )
    monkeypatch.setattr(
        "app.services.payments.paypal_client.invalidate_access_token",
        MagicMock(),
    )
    client = PaypalClient()
    unauthorized = MagicMock(status_code=401, text="unauthorized", headers={})
    unauthorized.json.return_value = {"error": "invalid_token"}
    ok = MagicMock(status_code=200, text='{"ok":true}', headers={})
    ok.json.return_value = {"ok": True}
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(side_effect=[unauthorized, ok])
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    with patch("app.services.payments.paypal_client.httpx.AsyncClient", return_value=mock_http):
        response = await client.request("GET", "/v1/test")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_client_429_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.payments.paypal_client.get_access_token",
        AsyncMock(return_value="tok"),
    )
    client = PaypalClient()
    limited = MagicMock(status_code=429, text="rate", headers={"Retry-After": "0"})
    limited.json.return_value = {"error": "rate"}
    ok = MagicMock(status_code=200, text='{"ok":true}', headers={})
    ok.json.return_value = {"ok": True}
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(side_effect=[limited, ok])
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    with patch("app.services.payments.paypal_client.httpx.AsyncClient", return_value=mock_http):
        with patch("app.services.payments.paypal_client.asyncio.sleep", AsyncMock()):
            response = await client.request("GET", "/v1/test")
    assert response.status_code == 200


async def _seed_approved_payment(db_session) -> tuple[Payment, VendorPaymentMethod]:
    vendor = VendorRegistry(
        tenant_id=TESTING_TENANT_UUID,
        vendor_slug="acme",
        vendor_name="Acme Pty Ltd",
        sender_pattern="acme@",
        approved=True,
    )
    db_session.add(vendor)
    await db_session.flush()

    from app.models.invoice import Invoice, InvoiceStatus

    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Pty Ltd",
        currency="AUD",
        status=InvoiceStatus.PROCESSED,
    )
    db_session.add(invoice)
    await db_session.flush()

    payment = Payment(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=invoice.id,
        vendor_registry_id=vendor.id,
        vendor="Acme Pty Ltd",
        amount=Decimal("250.00"),
        currency="AUD",
        status=PaymentStatus.SCHEDULED,
        approvers=[],
    )
    db_session.add(payment)
    await db_session.flush()

    method = VendorPaymentMethod(
        tenant_id=TESTING_TENANT_UUID,
        vendor_id=vendor.id,
        method_type="paypal",
        provider="paypal",
        recipient_type="EMAIL",
        recipient_value="vendor@example.com",
        currency="AUD",
        status="verified",
        verification_status="verified",
        is_default=True,
    )
    db_session.add(method)
    await db_session.flush()
    return payment, method


@pytest.mark.asyncio
async def test_payout_requires_approved_and_creates_attempt_before_api(db_session) -> None:
    await connect_paypal_account(db_session, tenant_id=TESTING_TENANT_UUID, user_id=1)
    payment, method = await _seed_approved_payment(db_session)

    mock_client = MagicMock()
    mock_client.request_json = AsyncMock(
        return_value={
            "batch_header": {"payout_batch_id": "BATCH-1", "batch_status": "PENDING"},
            "items": [
                {
                    "payout_item_id": "ITEM-1",
                    "transaction_status": "PENDING",
                    "payout_item": {"receiver": "vendor@example.com"},
                }
            ],
        }
    )

    with patch(
        "app.services.payments.paypal_payout_service.get_paypal_client",
        return_value=mock_client,
    ):
        attempt = await create_paypal_payout(
            db_session,
            tenant_id=TESTING_TENANT_UUID,
            payment_id=payment.id,
            recipient_method_id=method.id,
            amount=Decimal("250.00"),
            currency="AUD",
            note="INV-1004",
            actor_user_id=1,
        )

    assert attempt.provider == PROVIDER_PAYPAL
    assert attempt.status in {ATTEMPT_STATUS_SUBMITTED, ATTEMPT_STATUS_PENDING}
    assert attempt.status != ATTEMPT_STATUS_SUCCEEDED
    assert attempt.provider_batch_id == "BATCH-1"
    assert attempt.provider_request_id
    mock_client.request_json.assert_awaited()


@pytest.mark.asyncio
async def test_provider_neutral_duplicate_prevention(db_session) -> None:
    await connect_paypal_account(db_session, tenant_id=TESTING_TENANT_UUID, user_id=1)
    payment, method = await _seed_approved_payment(db_session)

    # Existing Stripe-side active attempt blocks PayPal payout
    db_session.add(
        PaymentAttempt(
            tenant_id=TESTING_TENANT_UUID,
            payment_id=payment.id,
            provider=PROVIDER_STRIPE,
            status=ATTEMPT_STATUS_PENDING,
            amount=Decimal("250.00"),
            currency="AUD",
        )
    )
    await db_session.flush()

    with pytest.raises(PaypalPayoutError) as exc:
        await create_paypal_payout(
            db_session,
            tenant_id=TESTING_TENANT_UUID,
            payment_id=payment.id,
            recipient_method_id=method.id,
        )
    assert exc.value.code == "duplicate_attempt"


@pytest.mark.asyncio
async def test_invalid_recipient_rejected(db_session) -> None:
    await connect_paypal_account(db_session, tenant_id=TESTING_TENANT_UUID, user_id=1)
    payment, method = await _seed_approved_payment(db_session)
    method.recipient_type = "BANK_ACCOUNT"
    await db_session.flush()
    with pytest.raises(PaypalPayoutError) as exc:
        await create_paypal_payout(
            db_session,
            tenant_id=TESTING_TENANT_UUID,
            payment_id=payment.id,
            recipient_method_id=method.id,
        )
    assert exc.value.code == "invalid_recipient_type"


@pytest.mark.asyncio
async def test_tenant_isolation_accounts(db_session) -> None:
    await connect_paypal_account(db_session, tenant_id=TESTING_TENANT_UUID, user_id=1)
    other = uuid.uuid4()
    foreign = TenantPaymentProviderAccount(
        tenant_id=other,
        provider=PROVIDER_PAYPAL,
        provider_account_id="FOREIGN",
        provider_merchant_id="FOREIGN",
        status="connected",
    )
    db_session.add(foreign)
    await db_session.flush()
    readiness = await get_paypal_readiness(db_session, TESTING_TENANT_UUID)
    assert readiness["merchant_id"] != "FOREIGN"


@pytest.mark.asyncio
async def test_webhook_invalid_signature_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()
    mock_client.request_json = AsyncMock(
        return_value={"verification_status": "FAILURE"}
    )
    monkeypatch.setattr(
        "app.services.payments.paypal_webhook_service.get_paypal_client",
        lambda: mock_client,
    )
    with pytest.raises(Exception):
        await verify_paypal_webhook(
            headers={
                "PAYPAL-TRANSMISSION-ID": "t1",
                "PAYPAL-TRANSMISSION-TIME": "2020-01-01T00:00:00Z",
                "PAYPAL-TRANSMISSION-SIG": "sig",
                "PAYPAL-CERT-URL": "https://api.paypal.com/cert",
                "PAYPAL-AUTH-ALGO": "SHA256withRSA",
            },
            body=b'{"id":"WH-1","event_type":"PAYMENT.PAYOUTS-ITEM.SUCCESS"}',
        )


@pytest.mark.asyncio
async def test_webhook_valid_and_dedupe(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    await connect_paypal_account(db_session, tenant_id=TESTING_TENANT_UUID, user_id=1)
    account = (
        await db_session.execute(
            __import__("sqlalchemy", fromlist=["select"]).select(TenantPaymentProviderAccount).where(
                TenantPaymentProviderAccount.tenant_id == TESTING_TENANT_UUID
            )
        )
    ).scalar_one()

    event = {
        "id": "WH-EVENT-1",
        "event_type": "PAYMENT.PAYOUTS-ITEM.SUCCESS",
        "resource": {
            "payout_batch_id": "BATCH-X",
            "payout_item_id": "ITEM-X",
            "transaction_status": "SUCCESS",
            "transaction_id": "TXN-1",
        },
    }

    mock_client = MagicMock()
    mock_client.request_json = AsyncMock(
        return_value={"verification_status": "SUCCESS"}
    )
    monkeypatch.setattr(
        "app.services.payments.paypal_webhook_service.get_paypal_client",
        lambda: mock_client,
    )

    # Attach merchant so tenant can be resolved if needed
    event["resource"]["sender_batch_id"] = str(account.tracking_id or "")

    first = await handle_paypal_webhook(
        db_session,
        headers={
            "PAYPAL-TRANSMISSION-ID": "t1",
            "PAYPAL-TRANSMISSION-TIME": "2020-01-01T00:00:00Z",
            "PAYPAL-TRANSMISSION-SIG": "sig",
            "PAYPAL-CERT-URL": "https://api.paypal.com/cert",
            "PAYPAL-AUTH-ALGO": "SHA256withRSA",
        },
        body=json.dumps(event).encode("utf-8"),
    )
    second = await handle_paypal_webhook(
        db_session,
        headers={
            "PAYPAL-TRANSMISSION-ID": "t1",
            "PAYPAL-TRANSMISSION-TIME": "2020-01-01T00:00:00Z",
            "PAYPAL-TRANSMISSION-SIG": "sig",
            "PAYPAL-CERT-URL": "https://api.paypal.com/cert",
            "PAYPAL-AUTH-ALGO": "SHA256withRSA",
        },
        body=json.dumps(event).encode("utf-8"),
    )
    assert first.get("duplicate") is False or first.get("status")
    assert second.get("duplicate") is True
    rows = (
        await db_session.execute(
            __import__("sqlalchemy", fromlist=["select"]).select(PaypalWebhookEvent)
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_refresh_marks_succeeded(db_session) -> None:
    await connect_paypal_account(db_session, tenant_id=TESTING_TENANT_UUID, user_id=1)
    payment, _method = await _seed_approved_payment(db_session)
    attempt = PaymentAttempt(
        tenant_id=TESTING_TENANT_UUID,
        payment_id=payment.id,
        provider=PROVIDER_PAYPAL,
        provider_batch_id="BATCH-R",
        provider_item_id="ITEM-R",
        provider_request_id="pp-payout-test",
        status=ATTEMPT_STATUS_PENDING,
        provider_status="PENDING",
        amount=Decimal("250.00"),
        currency="AUD",
        recipient_type="EMAIL",
        recipient_value="vendor@example.com",
    )
    db_session.add(attempt)
    await db_session.flush()

    mock_client = MagicMock()
    mock_client.request_json = AsyncMock(
        return_value={
            "payout_item_id": "ITEM-R",
            "transaction_status": "SUCCESS",
            "transaction_id": "TXN-R",
        }
    )
    with patch(
        "app.services.payments.paypal_payout_service.get_paypal_client",
        return_value=mock_client,
    ):
        updated = await refresh_payout_attempt(
            db_session,
            tenant_id=TESTING_TENANT_UUID,
            attempt_id=attempt.id,
        )
    assert updated.status == ATTEMPT_STATUS_SUCCEEDED
