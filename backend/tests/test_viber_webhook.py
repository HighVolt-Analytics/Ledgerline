"""Tests for Viber webhook signature verification."""

import hashlib
import hmac

from app.services.ingest.viber_client import ViberClient


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
    from app.services.ingest.viber_client import parse_viber_event

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
    from app.services.ingest.viber_client import parse_viber_event

    assert parse_viber_event({"event": "delivered"}) is None
