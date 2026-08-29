"""Stage 1 Integrations layer: core + Xero packages (not wired to HTTP yet)."""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import get_settings
from app.integrations.core.dispatch import send
from app.integrations.core.oauth_state import create_oauth_state, parse_oauth_state
from app.integrations.core.token_crypto import decrypt_secret, encrypt_secret
from app.integrations.xero.client import accounting_headers
from app.integrations.xero.connect_api import build_connect_url
from app.integrations.xero.oauth import authorize_url, is_configured, resolve_scopes


@pytest.fixture(autouse=True)
def _xero_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XERO_ENABLED", "true")
    monkeypatch.setenv("XERO_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("XERO_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv(
        "XERO_REDIRECT_URI",
        "http://localhost:8001/api/integrations/xero/callback",
    )
    monkeypatch.setenv(
        "XERO_SCOPES",
        "openid profile email offline_access accounting.settings "
        "accounting.contacts accounting.invoices accounting.attachments",
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_token_crypto_roundtrip() -> None:
    token = encrypt_secret("refresh-token-value")
    assert token != "refresh-token-value"
    assert decrypt_secret(token) == "refresh-token-value"


def test_oauth_state_roundtrip() -> None:
    tenant_id = uuid.uuid4()
    state = create_oauth_state(
        provider="xero",
        tenant_id=tenant_id,
        user_id=9,
        typ="xero_oauth",
    )
    payload = parse_oauth_state(state, provider="xero", typ="xero_oauth")
    assert payload["sub"] == "9"
    assert payload["org_id"] == str(tenant_id)
    assert payload["jti"]


def test_oauth_state_rejects_provider_mismatch() -> None:
    state = create_oauth_state(
        provider="xero",
        tenant_id=uuid.uuid4(),
        user_id=1,
        typ="xero_oauth",
    )
    with pytest.raises(ValueError, match="provider"):
        parse_oauth_state(state, provider="quickbooks_online", typ="xero_oauth")


def test_xero_authorize_url_uses_env_scopes_and_redirect() -> None:
    assert is_configured()
    assert "accounting.transactions" not in resolve_scopes()
    assert "accounting.invoices.read" not in resolve_scopes()
    url = authorize_url(state="abc")
    parsed = urlparse(url)
    assert parsed.netloc == "login.xero.com"
    query = parse_qs(parsed.query)
    assert query["redirect_uri"] == ["http://localhost:8001/api/integrations/xero/callback"]
    assert "accounting.invoices" in query["scope"][0]
    assert "accounting.invoices.read" not in query["scope"][0]


def test_connect_url_includes_state() -> None:
    url = build_connect_url(tenant_id=uuid.uuid4(), user_id=2)
    query = parse_qs(urlparse(url).query)
    assert query["state"]
    assert query["client_id"] == ["test-client-id"]


def test_accounting_headers() -> None:
    headers = accounting_headers(access_token="tok", xero_tenant_id="org-guid")
    assert headers["Authorization"] == "Bearer tok"
    assert headers["xero-tenant-id"] == "org-guid"


@pytest.mark.asyncio
async def test_dispatch_rejects_unknown_adapter() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        await send({}, ["quickbooks_online"])


@pytest.mark.asyncio
async def test_dispatch_xero_not_implemented_yet() -> None:
    with pytest.raises(NotImplementedError):
        await send({"invoice_id": 1}, ["xero"])
