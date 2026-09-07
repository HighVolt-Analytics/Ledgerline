"""Tests for Viber webhook signature verification."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import hashlib
import hmac

import pytest

from app.api.viber import viber_configured
from app.models.connected_viber import (
    STATUS_CONNECTED,
    STATUS_DISCONNECTED,
    ConnectedViberAccount,
)
from app.services.ingest.viber_client import (
    ViberClient,
    parse_viber_event,
    sender_id_from_event,
)
from app.services.ingest.viber_connection_service import disconnect_connection
from app.services.ingest.viber_ingest_service import (
    _REPLY_BY_KEY,
    ingest_viber_message,
    send_viber_welcome,
)


def test_verify_signature_valid() -> None:
    token = "test-viber-token"
    body = b'{"event":"message","message_token":123}'
    sig = hmac.new(token.encode("utf-8"), body, hashlib.sha256).hexdigest()
    client = ViberClient(token)
    assert client.verify_signature(body, sig) is True


def test_verify_signature_invalid() -> None:
    client = ViberClient("test-viber-token")
    body = b'{"event":"message"}'
    assert client.verify_signature(body, "bad-signature") is False


def test_parse_viber_picture_event() -> None:
    payload = {
        "event": "message",
        "message_token": 999,
        "sender": {"id": "abc123", "name": "Test"},
        "message": {
            "type": "picture",
            "media": "https://example.com/photo.jpg",
            "text": "receipt",
        },
    }
    msg = parse_viber_event(payload)
    assert msg is not None
    assert msg.sender_id == "abc123"
    assert msg.msg_type == "picture"
    assert msg.media_url == "https://example.com/photo.jpg"
    assert msg.text == "receipt"


def test_parse_viber_non_message_returns_none() -> None:
    assert parse_viber_event({"event": "delivered"}) is None
    assert parse_viber_event({"event": "subscribed", "user": {"id": "abc"}}) is None


def test_parse_viber_video_skips_ingest() -> None:
    msg = parse_viber_event(
        {
            "event": "message",
            "message_token": 1,
            "sender": {"id": "u1"},
            "message": {"type": "video", "media": "https://example.com/v.mp4"},
        }
    )
    assert msg is not None
    assert msg.skip_ingest is True
    assert msg.sender_id == "u1"


def test_sender_id_from_welcome_events() -> None:
    assert sender_id_from_event({"event": "subscribed", "user": {"id": "abc"}}) == "abc"
    assert (
        sender_id_from_event(
            {"event": "conversation_started", "user": {"id": "xyz"}}
        )
        == "xyz"
    )
    assert sender_id_from_event({"event": "delivered"}) == ""


def test_viber_configured_requires_connected_account() -> None:
    disconnected = ConnectedViberAccount()
    disconnected.connection_status = STATUS_DISCONNECTED
    disconnected.auth_token_encrypted = None
    assert viber_configured([]) is False
    assert viber_configured([disconnected]) is False

    connected = ConnectedViberAccount()
    connected.connection_status = STATUS_CONNECTED
    connected.auth_token_encrypted = "enc"
    assert viber_configured([connected]) is True


@pytest.mark.asyncio
async def test_welcome_sent_on_subscribed(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str]] = []

    async def fake_send(client, *, receiver_id: str, text: str, attempts: int = 3):
        sent.append((receiver_id, text))
        return {}

    monkeypatch.setattr(
        "app.services.ingest.viber_ingest_service.send_message_with_retry",
        fake_send,
    )
    ok = await send_viber_welcome(
        auth_token="test-viber-token",
        event={"event": "subscribed", "user": {"id": "abc123"}},
    )
    assert ok is True
    assert sent == [("abc123", _REPLY_BY_KEY["welcome"])]


@pytest.mark.asyncio
async def test_welcome_sent_on_conversation_started(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str]] = []

    async def fake_send(client, *, receiver_id: str, text: str, attempts: int = 3):
        sent.append((receiver_id, text))
        return {}

    monkeypatch.setattr(
        "app.services.ingest.viber_ingest_service.send_message_with_retry",
        fake_send,
    )
    ok = await send_viber_welcome(
        auth_token="test-viber-token",
        event={"event": "conversation_started", "user": {"id": "xyz"}},
    )
    assert ok is True
    assert sent == [("xyz", _REPLY_BY_KEY["welcome"])]


@pytest.mark.asyncio
async def test_welcome_not_sent_on_delivered(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str]] = []

    async def fake_send(client, *, receiver_id: str, text: str, attempts: int = 3):
        sent.append((receiver_id, text))
        return {}

    monkeypatch.setattr(
        "app.services.ingest.viber_ingest_service.send_message_with_retry",
        fake_send,
    )
    ok = await send_viber_welcome(
        auth_token="test-viber-token",
        event={"event": "delivered", "user": {"id": "abc123"}},
    )
    assert ok is False
    assert sent == []


@pytest.mark.asyncio
async def test_unsupported_video_sends_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str]] = []

    async def fake_send(client, *, receiver_id: str, text: str, attempts: int = 3):
        sent.append((receiver_id, text))
        return {}

    monkeypatch.setattr(
        "app.services.ingest.viber_ingest_service.send_message_with_retry",
        fake_send,
    )
    monkeypatch.setattr(
        "app.services.ingest.viber_ingest_service._audit_viber_skip",
        AsyncMock(),
    )

    connection = MagicMock()
    connection.tenant_id = uuid4()
    result = await ingest_viber_message(
        AsyncMock(),
        connection=connection,
        event={
            "event": "message",
            "message_token": 1,
            "sender": {"id": "u1"},
            "message": {"type": "video", "media": "https://example.com/v.mp4"},
        },
        auth_token="test-viber-token",
    )
    assert result.skipped_reason == "skipped_message_type"
    assert sent == [("u1", _REPLY_BY_KEY["unsupported_type"])]


@pytest.mark.asyncio
async def test_disconnect_unregisters_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []

    async def fake_set_webhook(self, url: str):
        urls.append(url)
        return {"status": 0}

    monkeypatch.setattr(ViberClient, "set_webhook", fake_set_webhook)
    monkeypatch.setattr(
        "app.services.ingest.viber_connection_service.decrypt_secret",
        lambda _value: "live-token",
    )

    connection = ConnectedViberAccount()
    connection.id = 1
    connection.bot_id = "bot-1"
    connection.auth_token_encrypted = "enc"
    connection.connection_status = STATUS_CONNECTED
    connection.integration_health = STATUS_CONNECTED

    session = AsyncMock()
    await disconnect_connection(session, connection)

    assert urls == [""]
    assert connection.auth_token_encrypted is None
    assert connection.connection_status == STATUS_DISCONNECTED
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_disconnect_clears_token_when_unregister_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(self, url: str):
        raise RuntimeError("viber unavailable")

    monkeypatch.setattr(ViberClient, "set_webhook", boom)
    monkeypatch.setattr(
        "app.services.ingest.viber_connection_service.decrypt_secret",
        lambda _value: "live-token",
    )

    connection = ConnectedViberAccount()
    connection.id = 2
    connection.bot_id = "bot-2"
    connection.auth_token_encrypted = "enc"
    connection.connection_status = STATUS_CONNECTED

    session = AsyncMock()
    await disconnect_connection(session, connection)

    assert connection.auth_token_encrypted is None
    assert connection.connection_status == STATUS_DISCONNECTED
    session.flush.assert_awaited()
