"""PUBLIC_TUNNEL_URL / ngrok configuration."""

import pytest

from app.config import Settings, get_settings
from app.services.public_app_url import build_public_app_path, resolve_public_app_base_url


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


def test_build_public_app_path_uses_tunnel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "PUBLIC_TUNNEL_URL",
        "https://example.ngrok-free.dev",
    )
    get_settings.cache_clear()
    assert resolve_public_app_base_url() == "https://example.ngrok-free.dev"
    url = build_public_app_path("/connect-mailbox?token=abc")
    assert url.startswith("https://example.ngrok-free.dev/connect-mailbox?token=abc")
