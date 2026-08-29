"""Accounting integration OAuth tests â€” connect/status/disconnect only."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import get_settings
from app.models.accounting_integration import (
    AccountingIntegration,
    AccountingIntegrationStatus,
    AccountingProvider,
)
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services.integration.accounting_integration_service import (
    build_connect_url,
    complete_oauth_callback,
    create_oauth_state,
    disconnect_integration,
    integration_status_item,
    parse_oauth_state,
    quickbooks_configured,
    xero_configured,
)
from app.services.auth.auth_service import hash_password
from app.services.auth.membership_service import ensure_membership
from app.services.shared.token_vault import decrypt_secret, encrypt_secret
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.fixture(autouse=True)
def _accounting_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XERO_CLIENT_ID", "xero-client")
    monkeypatch.setenv("XERO_CLIENT_SECRET", "xero-secret")
    monkeypatch.setenv(
        "XERO_REDIRECT_URI",
        "http://localhost:8001/api/integrations/xero/callback",
    )
    monkeypatch.setenv("QUICKBOOKS_CLIENT_ID", "qbo-client")
    monkeypatch.setenv("QUICKBOOKS_CLIENT_SECRET", "qbo-secret")
    monkeypatch.setenv(
        "QUICKBOOKS_REDIRECT_URI",
        "http://localhost:8001/api/integrations/quickbooks/callback",
    )
    monkeypatch.setenv(
        "ACCOUNTING_OAUTH_FRONTEND_RETURN_URL",
        "http://localhost:5173/integrations",
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_xero_oauth_state_roundtrip() -> None:
    state = create_oauth_state(
        provider=AccountingProvider.XERO.value,
        tenant_id=TESTING_TENANT_UUID,
        user_id=3,
    )
    payload = parse_oauth_state(state, provider=AccountingProvider.XERO.value)
    assert payload["sub"] == "3"
    assert payload["typ"] == "xero_oauth"


def test_quickbooks_oauth_state_roundtrip() -> None:
    state = create_oauth_state(
        provider=AccountingProvider.QUICKBOOKS_ONLINE.value,
        tenant_id=TESTING_TENANT_UUID,
        user_id=5,
    )
    payload = parse_oauth_state(state, provider=AccountingProvider.QUICKBOOKS_ONLINE.value)
    assert payload["sub"] == "5"
    assert payload["typ"] == "quickbooks_oauth"


def test_oauth_state_rejects_provider_mismatch() -> None:
    state = create_oauth_state(
        provider=AccountingProvider.XERO.value,
        tenant_id=TESTING_TENANT_UUID,
        user_id=1,
    )
    with pytest.raises(ValueError):
        parse_oauth_state(state, provider=AccountingProvider.QUICKBOOKS_ONLINE.value)


def test_provider_configured_flags() -> None:
    assert xero_configured()
    assert quickbooks_configured()


def test_build_connect_urls_include_provider_hosts() -> None:
    xero_url = build_connect_url(
        provider=AccountingProvider.XERO.value,
        tenant_id=TESTING_TENANT_UUID,
        user_id=1,
    )
    qbo_url = build_connect_url(
        provider=AccountingProvider.QUICKBOOKS_ONLINE.value,
        tenant_id=TESTING_TENANT_UUID,
        user_id=1,
    )
    assert "login.xero.com" in xero_url
    assert "appcenter.intuit.com" in qbo_url


def test_integration_status_item_disconnected_when_missing() -> None:
    item = integration_status_item(AccountingProvider.XERO.value, None)
    assert item["status"] == AccountingIntegrationStatus.DISCONNECTED.value
    assert item["display_name"] is None


@pytest.mark.asyncio
async def test_disconnect_clears_encrypted_tokens(db_session) -> None:
    row = AccountingIntegration(
        tenant_id=TESTING_TENANT_UUID,
        provider=AccountingProvider.XERO.value,
        status=AccountingIntegrationStatus.CONNECTED.value,
        display_name="Demo Org",
        provider_tenant_id="xero-tenant-1",
        access_token_encrypted=encrypt_secret("access"),
        refresh_token_encrypted=encrypt_secret("refresh"),
    )
    db_session.add(row)
    await db_session.flush()

    updated = await disconnect_integration(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        provider=AccountingProvider.XERO.value,
    )
    assert updated is not None
    assert updated.status == AccountingIntegrationStatus.DISCONNECTED.value
    assert updated.access_token_encrypted is None
    assert updated.refresh_token_encrypted is None


@pytest.mark.asyncio
async def test_status_endpoint_returns_providers(client) -> None:
    res = await client.get("/api/integrations/status")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["xero"]["status"] == "disconnected"
    assert data["quickbooks_online"]["status"] == "disconnected"
    assert data["xero"]["configured"] is True


@pytest.mark.asyncio
async def test_connect_returns_url_when_configured(client) -> None:
    res = await client.get("/api/integrations/xero/connect")
    assert res.status_code == 200
    assert "login.xero.com" in res.json()["data"]["connect_url"]


@pytest.mark.asyncio
async def test_connect_not_configured_returns_503(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XERO_CLIENT_ID", "")
    monkeypatch.setenv("XERO_CLIENT_SECRET", "")
    get_settings.cache_clear()
    res = await client.get("/api/integrations/xero/connect")
    assert res.status_code == 503


@pytest.mark.asyncio
async def test_xero_callback_public_no_401(client) -> None:
    state = create_oauth_state(
        provider=AccountingProvider.XERO.value,
        tenant_id=TESTING_TENANT_UUID,
        user_id=999_999,
    )
    res = await client.get(
        "/api/integrations/xero/callback",
        params={"code": "code", "state": state},
        follow_redirects=False,
    )
    assert res.status_code != 401
    location = res.headers.get("location", "")
    assert "xero=error" in location


@pytest.mark.asyncio
async def test_disconnect_clears_only_current_tenant(db_session, client) -> None:
    other_tenant_id = uuid.uuid4()
    db_session.add(Tenant(id=other_tenant_id, name="Other", slug="other"))
    connected = AccountingIntegration(
        tenant_id=TESTING_TENANT_UUID,
        provider=AccountingProvider.XERO.value,
        status=AccountingIntegrationStatus.CONNECTED.value,
        display_name="Primary Org",
        provider_tenant_id="xero-primary",
        access_token_encrypted=encrypt_secret("token-a"),
    )
    db_session.add(connected)
    await db_session.flush()

    res = await client.post("/api/integrations/xero/disconnect")
    assert res.status_code == 200

    await db_session.refresh(connected)
    assert connected.status == AccountingIntegrationStatus.DISCONNECTED.value
    assert connected.access_token_encrypted is None


@pytest.mark.asyncio
async def test_exchange_xero_code_stores_encrypted_tokens(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = User(
        tenant_id=TESTING_TENANT_UUID,
        email="acct-admin@example.com",
        password_hash=hash_password("password123"),
        full_name="Acct Admin",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(admin)
    await db_session.flush()
    await ensure_membership(
        db_session, user_id=admin.id, tenant_id=TESTING_TENANT_UUID, role="admin"
    )

    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json.return_value = {
        "access_token": "xero-access",
        "refresh_token": "xero-refresh",
        "expires_in": 1800,
        "scope": "openid offline_access",
    }
    connections_response = MagicMock()
    connections_response.status_code = 200
    connections_response.json.return_value = [
        {"id": "conn-1", "tenantId": "org-uuid", "tenantName": "Demo Company", "tenantType": "ORGANISATION"}
    ]

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=token_response)
    mock_client.get = AsyncMock(return_value=connections_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(
        "app.integrations.xero.oauth.httpx.AsyncClient",
        lambda *args, **kwargs: mock_client,
    )

    from app.integrations.xero.connect_api import complete_oauth_callback as xero_complete

    row = await xero_complete(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        user_id=admin.id,
        code="auth-code",
    )
    assert row.status == AccountingIntegrationStatus.CONNECTED.value
    assert row.display_name == "Demo Company"
    assert row.provider_tenant_id == "org-uuid"
    assert decrypt_secret(row.access_token_encrypted or "") == "xero-access"
    assert decrypt_secret(row.refresh_token_encrypted or "") == "xero-refresh"

