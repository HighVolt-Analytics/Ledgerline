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


from tests.auth_test_helpers import seed_admin_user


@pytest.mark.asyncio
async def test_admin_consent_url_endpoint_returns_url(client: AsyncClient, db_session) -> None:
    _, token = await seed_admin_user(
        db_session,
        email="ga@consent.example.com",
        tenant_slug="hv-org",
        full_name="GA Admin",
    )
    await db_session.commit()
    res = await client.get(
        "/api/mailboxes/oauth/admin-consent-url",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    body = res.json()["data"]
    assert "adminconsent" in body["admin_consent_url"]
    assert body["instructions"]
