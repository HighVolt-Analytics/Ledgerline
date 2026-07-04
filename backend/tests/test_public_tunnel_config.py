"""PUBLIC_TUNNEL_URL / ngrok configuration."""

import pytest

from app.config import Settings, get_settings
from app.services.shared.public_app_url import build_public_app_path, resolve_public_app_base_url


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_public_tunnel_overrides_local_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "PUBLIC_TUNNEL_URL",
        "https://abridge-landowner-nutlike.ngrok-free.dev",
    )
    monkeypatch.setenv("PUBLIC_APP_URL", "http://localhost:5173")
    monkeypatch.setenv(
        "GRAPH_OAUTH_REDIRECT_URI",
        "http://localhost:8001/api/mailboxes/oauth/callback",
    )
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")

    settings = Settings()
    assert settings.public_app_url == "https://abridge-landowner-nutlike.ngrok-free.dev"
    assert (
        settings.graph_oauth_redirect_uri
        == "https://abridge-landowner-nutlike.ngrok-free.dev/api/mailboxes/oauth/callback"
    )
    assert "https://abridge-landowner-nutlike.ngrok-free.dev" in settings.cors_origin_list


def test_public_tunnel_overrides_gmail_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "PUBLIC_TUNNEL_URL",
        "https://abridge-landowner-nutlike.ngrok-free.dev",
    )
    monkeypatch.setenv(
        "GMAIL_OAUTH_REDIRECT_URI",
        "http://localhost:8001/api/mailboxes/gmail/oauth/callback",
    )

    settings = Settings()
    assert (
        settings.gmail_oauth_redirect_uri
        == "https://abridge-landowner-nutlike.ngrok-free.dev/api/mailboxes/gmail/oauth/callback"
    )


def test_azure_webapp_overrides_localhost_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_TUNNEL_URL", "")
    monkeypatch.setenv("NGROK_URL", "")
    monkeypatch.setenv("PUBLIC_APP_URL", "http://localhost:5173")
    monkeypatch.setenv(
        "GRAPH_OAUTH_FRONTEND_RETURN_URL",
        "http://localhost:5173/integrations",
    )
    monkeypatch.setenv(
        "GRAPH_OAUTH_REDIRECT_URI",
        "http://localhost:8001/api/mailboxes/oauth/callback",
    )
    monkeypatch.setenv("AZURE_WEBAPP_URL", "https://staging.highvolt.tech/ledgerlink")

    settings = Settings()
    assert settings.public_app_url == "https://staging.highvolt.tech/ledgerlink"
    assert (
        settings.graph_oauth_frontend_return_url
        == "https://staging.highvolt.tech/ledgerlink/integrations"
    )
    assert (
        settings.graph_oauth_redirect_uri
        == "https://staging.highvolt.tech/ledgerlink/api/mailboxes/oauth/callback"
    )
    get_settings.cache_clear()
    assert resolve_public_app_base_url() == "https://staging.highvolt.tech/ledgerlink"
    url = build_public_app_path("/connect-mailbox?token=abc")
    assert url == "https://staging.highvolt.tech/ledgerlink/connect-mailbox?token=abc"


def test_build_public_app_path_appends_root_path_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_APP_URL", "https://staging.highvolt.tech")
    monkeypatch.setenv("AZURE_WEBAPP_URL", "")
    monkeypatch.setenv("PUBLIC_TUNNEL_URL", "")
    monkeypatch.setenv("BASE_PATH", "/ledgerlink")
    get_settings.cache_clear()
    assert (
        build_public_app_path("/vault?invoice=40")
        == "https://staging.highvolt.tech/ledgerlink/vault?invoice=40"
    )


def test_vault_view_path_uses_azure_webapp_on_staging(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.audit.audit_export_service import vault_view_path

    monkeypatch.setenv("PUBLIC_APP_URL", "http://localhost:5173")
    monkeypatch.setenv("AZURE_WEBAPP_URL", "https://staging.highvolt.tech/ledgerlink")
    monkeypatch.setenv("PUBLIC_TUNNEL_URL", "")
    monkeypatch.setenv("BASE_PATH", "/ledgerlink")
    get_settings.cache_clear()
    assert (
        vault_view_path(40)
        == "https://staging.highvolt.tech/ledgerlink/vault?invoice=40"
    )


def test_build_public_app_path_uses_tunnel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "PUBLIC_TUNNEL_URL",
        "https://example.ngrok-free.dev",
    )
    get_settings.cache_clear()
    assert resolve_public_app_base_url() == "https://example.ngrok-free.dev"
    url = build_public_app_path("/connect-mailbox?token=abc")
    assert url.startswith("https://example.ngrok-free.dev/connect-mailbox?token=abc")
