"""Microsoft login authority must not inherit AZURE_TENANT_ID."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.services.auth.oauth_login_service import _microsoft_authority, build_microsoft_authorize_url


def test_microsoft_oauth_authority_defaults_to_common_even_with_azure_tenant(
    monkeypatch,
):
    monkeypatch.setenv("AZURE_TENANT_ID", "54904ca2-e5a0-481c-a10a-73242e6476ea")
    monkeypatch.delenv("MICROSOFT_OAUTH_AUTHORITY_TENANT", raising=False)
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_ID", "b7dea16f-a312-47b9-9754-9b109ea92902")
    monkeypatch.setenv("MICROSOFT_OAUTH_REDIRECT_URI", "http://localhost:5173/login/oauth/callback")
    get_settings.cache_clear()
    settings = Settings()
    assert settings.microsoft_oauth_authority_tenant == "common"
    assert settings.azure_tenant_id == "54904ca2-e5a0-481c-a10a-73242e6476ea"
    get_settings.cache_clear()
    monkeypatch.setenv("MICROSOFT_OAUTH_AUTHORITY_TENANT", "common")
    assert _microsoft_authority() == "https://login.microsoftonline.com/common"


def test_microsoft_authorize_url_uses_common_authority(monkeypatch):
    monkeypatch.setenv("AZURE_TENANT_ID", "54904ca2-e5a0-481c-a10a-73242e6476ea")
    monkeypatch.setenv("MICROSOFT_OAUTH_AUTHORITY_TENANT", "common")
    monkeypatch.setenv("MICROSOFT_OAUTH_CLIENT_ID", "b7dea16f-a312-47b9-9754-9b109ea92902")
    monkeypatch.setenv("MICROSOFT_OAUTH_REDIRECT_URI", "http://localhost:5173/login/oauth/callback")
    get_settings.cache_clear()
    url = build_microsoft_authorize_url(
        intent="login",
        state="test-state",
        pkce_challenge="challenge",
    )
    assert url.startswith("https://login.microsoftonline.com/common/oauth2/v2.0/authorize?")
    assert "54904ca2" not in url
