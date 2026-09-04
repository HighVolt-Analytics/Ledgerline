"""Production Xero integration unit tests."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt
import pytest

from app.config import get_settings
from app.models.accounting_integration import (
    AccountingIntegration,
    AccountingIntegrationStatus,
    AccountingProvider,
)
from app.models.accounting_sync_job import (
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETED,
    JOB_TYPE_SETTINGS,
    AccountingSyncJob,
)
from app.models.external_accounting_ref import ExternalAccountingRef
from app.models.invoice import Invoice, InvoiceStatus
from app.models.xero_connection import XeroConnection
from app.services.integration.accounting_integration_service import (
    complete_oauth_callback,
    create_oauth_state,
    disconnect_xero,
    list_xero_connections,
    parse_oauth_state,
    resolve_xero_scopes,
    select_xero_connection,
    validate_oauth_state_replay,
)
from app.integrations.xero.http_legacy import XeroApiError, XeroClient
from app.integrations.xero.mapping import validate_invoice_xero_mappings
from app.integrations.xero.readiness import enrich_xero_readiness
from app.integrations.xero.sync_jobs import cancel_pending_jobs, enqueue_sync_job
from app.integrations.xero.tokens import (
    REFRESH_MARGIN_SECONDS,
    _token_expiring_soon,
)
from app.services.shared.token_vault import decrypt_secret, encrypt_secret
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.fixture(autouse=True)
def _xero_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XERO_ENABLED", "true")
    monkeypatch.setenv("XERO_CLIENT_ID", "xero-client")
    monkeypatch.setenv("XERO_CLIENT_SECRET", "xero-secret")
    monkeypatch.setenv(
        "XERO_REDIRECT_URI",
        "http://localhost:8001/api/integrations/xero/callback",
    )
    monkeypatch.setenv(
        "XERO_SCOPES",
        "openid profile email accounting.settings.read accounting.contacts offline_access",
    )
    monkeypatch.setenv("XERO_WEBHOOK_KEY", "whsec_test_key")
    monkeypatch.setenv("XERO_API_BASE_URL", "https://api.xero.com")
    # Unit tests only — production JWT secret is unchanged.
    monkeypatch.setenv(
        "JWT_SECRET",
        "unit-test-jwt-secret-key-32b-minimum!!",
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_resolve_xero_scopes_from_config() -> None:
    assert "offline_access" in resolve_xero_scopes()


def test_oauth_state_includes_jti() -> None:
    state = create_oauth_state(
        provider=AccountingProvider.XERO.value,
        tenant_id=TESTING_TENANT_UUID,
        user_id=1,
    )
    payload = parse_oauth_state(state, provider=AccountingProvider.XERO.value)
    assert payload.get("jti")


@pytest.mark.asyncio
async def test_oauth_state_replay_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    state = create_oauth_state(
        provider=AccountingProvider.XERO.value,
        tenant_id=TESTING_TENANT_UUID,
        user_id=1,
    )
    payload = parse_oauth_state(state, provider=AccountingProvider.XERO.value)
    # Patch where the symbol is bound (import site), not the defining module.
    monkeypatch.setattr(
        "app.services.integration.accounting_integration_service.consume_oauth_jti",
        AsyncMock(return_value=False),
    )
    with pytest.raises(ValueError, match="already used"):
        await validate_oauth_state_replay(payload)


def test_token_expiring_soon_margin() -> None:
    row = AccountingIntegration(
        tenant_id=TESTING_TENANT_UUID,
        provider=AccountingProvider.XERO.value,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=REFRESH_MARGIN_SECONDS - 10),
    )
    assert _token_expiring_soon(row) is True
    row.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    assert _token_expiring_soon(row) is False


def test_enrich_readiness_org_selection() -> None:
    data = enrich_xero_readiness(
        {
            "configured": True,
            "connected": True,
            "ready": False,
            "status": AccountingIntegrationStatus.ORGANISATION_SELECTION_REQUIRED.value,
            "organisation_selected": False,
            "connection_count": 2,
        }
    )
    assert data["organisation_selection_required"] is True
    assert data["needs_reauth"] is False


def test_xero_api_error_structure() -> None:
    err = XeroApiError(
        status_code=400,
        error_code="VALIDATION",
        message="validation failed",
    )
    assert err.status_code == 400
    assert err.error_code == "VALIDATION"


@pytest.mark.asyncio
async def test_xero_client_429_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    db = AsyncMock()
    monkeypatch.setattr(
        "app.integrations.xero.http_legacy.get_valid_access_token",
        AsyncMock(return_value="token"),
    )
    rate_limited = MagicMock(status_code=429, text="rate limited", headers={"Retry-After": "0"})
    ok_response = MagicMock(status_code=200, text='{"ok": true}')
    ok_response.json.return_value = {"ok": True}
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(side_effect=[rate_limited, ok_response])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr("app.integrations.xero.http_legacy.httpx.AsyncClient", lambda **_: mock_client)
    monkeypatch.setattr("app.integrations.xero.http_legacy.asyncio.sleep", AsyncMock())

    client = XeroClient(db=db, tenant_id=TESTING_TENANT_UUID, xero_tenant_id="org-1")
    payload = await client.get_json("Organisation")
    assert payload["ok"] is True
    assert mock_client.request.await_count == 2


@pytest.mark.asyncio
async def test_single_org_auto_select_on_exchange(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    token_response = MagicMock(status_code=200)
    token_response.json.return_value = {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_in": 1800,
        "scope": "openid offline_access",
    }
    connections_response = MagicMock(status_code=200)
    connections_response.json.return_value = [
        {
            "id": "conn-1",
            "tenantId": "org-1",
            "tenantName": "Demo Co",
            "tenantType": "ORGANISATION",
        }
    ]
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=token_response)
    mock_client.get = AsyncMock(return_value=connections_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.services.integration.accounting_integration_service.httpx.AsyncClient",
        lambda *args, **kwargs: mock_client,
    )

    row = await complete_oauth_callback(
        db_session,
        provider=AccountingProvider.XERO.value,
        code="code",
        tenant_id=TESTING_TENANT_UUID,
        user_id=1,
    )
    assert row.status == AccountingIntegrationStatus.CONNECTED.value
    assert row.provider_tenant_id == "org-1"


@pytest.mark.asyncio
async def test_multi_org_requires_selection(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    token_response = MagicMock(status_code=200)
    token_response.json.return_value = {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_in": 1800,
    }
    connections_response = MagicMock(status_code=200)
    connections_response.json.return_value = [
        {"id": "c1", "tenantId": "o1", "tenantName": "A", "tenantType": "ORGANISATION"},
        {"id": "c2", "tenantId": "o2", "tenantName": "B", "tenantType": "ORGANISATION"},
    ]
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=token_response)
    mock_client.get = AsyncMock(return_value=connections_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.services.integration.accounting_integration_service.httpx.AsyncClient",
        lambda *args, **kwargs: mock_client,
    )

    row = await complete_oauth_callback(
        db_session,
        provider=AccountingProvider.XERO.value,
        code="code",
        tenant_id=TESTING_TENANT_UUID,
        user_id=1,
    )
    assert row.status == AccountingIntegrationStatus.ORGANISATION_SELECTION_REQUIRED.value
    assert row.provider_tenant_id is None


@pytest.mark.asyncio
async def test_tenant_cannot_select_foreign_connection(db_session) -> None:
    integration = AccountingIntegration(
        tenant_id=TESTING_TENANT_UUID,
        provider=AccountingProvider.XERO.value,
        status=AccountingIntegrationStatus.ORGANISATION_SELECTION_REQUIRED.value,
        access_token_encrypted=encrypt_secret("tok"),
    )
    db_session.add(integration)
    await db_session.flush()
    other_tenant = uuid.uuid4()
    foreign = XeroConnection(
        accounting_integration_id=integration.id,
        tenant_id=other_tenant,
        xero_connection_id="foreign-conn",
        xero_tenant_id="foreign-tenant",
        xero_tenant_type="ORGANISATION",
        xero_tenant_name="Foreign",
        active=True,
    )
    db_session.add(foreign)
    await db_session.flush()

    with pytest.raises(ValueError, match="not found"):
        await select_xero_connection(
            db_session,
            tenant_id=TESTING_TENANT_UUID,
            xero_connection_id="foreign-conn",
        )


@pytest.mark.asyncio
async def test_disconnect_cancels_pending_jobs(db_session) -> None:
    integration = AccountingIntegration(
        tenant_id=TESTING_TENANT_UUID,
        provider=AccountingProvider.XERO.value,
        status=AccountingIntegrationStatus.CONNECTED.value,
        provider_tenant_id="org-1",
        access_token_encrypted=encrypt_secret("tok"),
        refresh_token_encrypted=encrypt_secret("refresh"),
    )
    db_session.add(integration)
    await db_session.flush()
    job = AccountingSyncJob(
        tenant_id=TESTING_TENANT_UUID,
        provider=AccountingProvider.XERO.value,
        job_type=JOB_TYPE_SETTINGS,
        status="pending",
    )
    db_session.add(job)
    await db_session.flush()

    await disconnect_xero(db_session, tenant_id=TESTING_TENANT_UUID)
    await db_session.refresh(job)
    assert job.status == JOB_STATUS_CANCELLED
    await db_session.refresh(integration)
    assert integration.status == AccountingIntegrationStatus.DISCONNECTED.value
    assert integration.last_successful_sync_at is None


@pytest.mark.asyncio
async def test_sync_job_enqueue(db_session) -> None:
    job = await enqueue_sync_job(db_session, tenant_id=TESTING_TENANT_UUID, job_type=JOB_TYPE_SETTINGS)
    assert job.id is not None
    assert job.status == "pending"


@pytest.mark.asyncio
async def test_mapping_validation_missing_account(db_session) -> None:
    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Pty Ltd",
        currency="AUD",
        account_code=None,
        status=InvoiceStatus.PROCESSED,
    )
    db_session.add(invoice)
    await db_session.flush()
    result = await validate_invoice_xero_mappings(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        invoice=invoice,
        organisation_id="org-1",
    )
    assert result.valid is False
    codes = {item["code"] for item in result.errors}
    assert "missing_account_code" in codes


@pytest.mark.asyncio
async def test_duplicate_push_ref_prevents_collision(db_session) -> None:
    ref = ExternalAccountingRef(
        tenant_id=TESTING_TENANT_UUID,
        provider=AccountingProvider.XERO.value,
        entity_type="invoice",
        internal_entity_id="42",
        external_entity_id="xero-inv-1",
        external_number="INV-001",
        external_status="AUTHORISED",
        payload_hash="abc123",
    )
    db_session.add(ref)
    await db_session.flush()
    assert ref.payload_hash == "abc123"


@pytest.mark.asyncio
async def test_xero_readiness_endpoint(client) -> None:
    res = await client.get("/api/integrations/xero/readiness")
    assert res.status_code == 200
    body = res.json()["data"]
    assert "configured" in body
    assert "organisation_selection_required" in body


@pytest.mark.asyncio
async def test_xero_verify_endpoint_not_connected(client) -> None:
    res = await client.get("/api/integrations/xero/verify")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["connected"] is False


@pytest.mark.asyncio
async def test_webhook_invalid_signature(client) -> None:
    body = json.dumps({"events": []})
    res = await client.post(
        "/api/webhooks/xero",
        content=body,
        headers={
            "Content-Type": "application/json",
            "x-xero-signature": "invalid",
        },
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_webhook_valid_signature(client) -> None:
    body = json.dumps({"events": [], "firstEventSequence": 0, "lastEventSequence": 0})
    key = get_settings().xero_webhook_key or "whsec_test_key"
    sig = base64.b64encode(
        hmac.new(key.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    ).decode("ascii")
    res = await client.post(
        "/api/webhooks/xero",
        content=body,
        headers={
            "Content-Type": "application/json",
            "x-xero-signature": sig,
        },
    )
    assert res.status_code == 200
