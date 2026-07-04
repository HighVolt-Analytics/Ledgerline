"""Tests for Meta WhatsApp webhook verification."""

from app.config import get_settings
from app.services.ingest.whatsapp_graph_client import verify_webhook_signature


def test_verify_webhook_signature_valid(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("META_APP_SECRET", "test-secret")
    monkeypatch.setenv("META_APP_ID", "123")
    monkeypatch.setenv("META_WEBHOOK_VERIFY_TOKEN", "tok")
    body = b'{"object":"whatsapp_business_account"}'
    import hashlib
    import hmac

    sig = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, f"sha256={sig}")


def test_meta_webhook_verify_token_from_settings(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("META_WEBHOOK_VERIFY_TOKEN", "my-verify-token")
    monkeypatch.setenv("META_APP_ID", "123")
    monkeypatch.setenv("META_APP_SECRET", "sec")
    settings = get_settings()
    assert settings.whatsapp_effective_verify_token == "my-verify-token"
