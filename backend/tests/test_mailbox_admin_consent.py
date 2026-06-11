"""Admin consent URL for delegated mailbox OAuth."""

import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.services.mailbox_oauth_service import build_admin_consent_url


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_TENANT_ID", "54904ca2-e5a0-481c-a10a-73242e6476ea")
    monkeypatch.setenv("AZURE_CLIENT_ID", "b7dea16f-a312-47b9-9754-9b109ea92902")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv(
        "GRAPH_OAUTH_REDIRECT_URI",
        "http://localhost:8001/api/mailboxes/oauth/callback",
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_build_admin_consent_url_includes_tenant_client_and_scopes() -> None:
    url = build_admin_consent_url()
    assert "54904ca2-e5a0-481c-a10a-73242e6476ea" in url
    assert "b7dea16f-a312-47b9-9754-9b109ea92902" in url
    assert "/v2.0/adminconsent" in url
    assert "Mail.ReadWrite" in url
    assert "User.Read" in url


@pytest.mark.asyncio
async def test_admin_consent_url_endpoint_requires_admin(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    res = await client.get("/api/mailboxes/oauth/admin-consent-url")
    assert res.status_code == 401
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_admin_consent_url_endpoint_returns_url(client: AsyncClient) -> None:
    reg = await client.post(
        "/api/auth/register",
        json={
            "email": "ga@consent.example.com",
            "password": "securepass1",
            "full_name": "GA Admin",
            "org_name": "Consent Org",
            "org_slug": "consent-org",
        },
    )
    token = reg.json()["data"]["access_token"]
    res = await client.get(
        "/api/mailboxes/oauth/admin-consent-url",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    body = res.json()["data"]
    assert "adminconsent" in body["admin_consent_url"]
    assert body["instructions"]
