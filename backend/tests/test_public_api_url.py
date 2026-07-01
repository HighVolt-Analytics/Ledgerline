"""Public Meta / WhatsApp URL builders for local and AKS staging."""

from app.config import get_settings
from app.services.public_api_url import (
    resolve_public_api_base_url,
    webhook_meta_url,
    whatsapp_oauth_callback_url,
)


def test_webhook_and_oauth_urls_for_staging(monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_TUNNEL_URL", "")
    monkeypatch.setenv("NGROK_URL", "")
    monkeypatch.setenv(
        "WHATSAPP_OAUTH_REDIRECT_URI",
        "https://staging.highvolt.tech/ledgerlink/auth/whatsapp/callback",
    )
    monkeypatch.setenv("AZURE_WEBAPP_URL", "https://staging.highvolt.tech/ledgerlink")
    get_settings.cache_clear()

    assert (
        webhook_meta_url()
        == "https://staging.highvolt.tech/ledgerlink/webhook/meta"
    )
    assert (
        whatsapp_oauth_callback_url()
        == "https://staging.highvolt.tech/ledgerlink/auth/whatsapp/callback"
    )


def test_webhook_url_local_default(monkeypatch) -> None:
    monkeypatch.delenv("WHATSAPP_OAUTH_REDIRECT_URI", raising=False)
    monkeypatch.setenv("AZURE_WEBAPP_URL", "")
    monkeypatch.setenv("PUBLIC_TUNNEL_URL", "")
    monkeypatch.setenv("NGROK_URL", "")
    get_settings.cache_clear()

    assert resolve_public_api_base_url() == "http://localhost:8001"
    assert webhook_meta_url() == "http://localhost:8001/webhook/meta"
    assert (
        whatsapp_oauth_callback_url()
        == "http://localhost:8001/auth/whatsapp/callback"
    )
