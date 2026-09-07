"""Tests for Slack webhook signature, parsing, and ingest identity rules."""

from __future__ import annotations

import hashlib
import hmac
import time
from unittest.mock import AsyncMock, patch

import pytest

from app.config import get_settings
from app.services.ingest.slack_web_client import (
    parse_slack_payload,
    verify_slack_signature,
)


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    basestring = b"v0:" + timestamp.encode("utf-8") + b":" + body
    return "v0=" + hmac.new(secret.encode("utf-8"), basestring, hashlib.sha256).hexdigest()


def test_verify_slack_signature_valid(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test-signing-secret")
    monkeypatch.setenv("SLACK_CLIENT_ID", "cid")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "csec")
    get_settings.cache_clear()
    body = b'{"type":"event_callback"}'
    ts = str(int(time.time()))
    sig = _sign("test-signing-secret", ts, body)
    assert verify_slack_signature(body, ts, sig) is True


def test_verify_slack_signature_missing(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test-signing-secret")
    monkeypatch.setenv("SLACK_CLIENT_ID", "cid")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "csec")
    get_settings.cache_clear()
    body = b"{}"
    assert verify_slack_signature(body, str(int(time.time())), None) is False
    assert verify_slack_signature(body, None, "v0=abc") is False


def test_verify_slack_signature_stale(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test-signing-secret")
    monkeypatch.setenv("SLACK_CLIENT_ID", "cid")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "csec")
    get_settings.cache_clear()
    body = b'{"ok":true}'
    ts = str(int(time.time()) - 600)
    sig = _sign("test-signing-secret", ts, body)
    assert verify_slack_signature(body, ts, sig) is False


def test_parse_skips_bot_and_subtypes() -> None:
    messages, life = parse_slack_payload(
        {
            "type": "event_callback",
            "event_id": "Ev1",
            "team_id": "T1",
            "event": {
                "type": "message",
                "bot_id": "B1",
                "channel": "D1",
                "user": "U1",
                "ts": "1.0",
            },
        }
    )
    assert messages == []
    assert life == []

    messages, _ = parse_slack_payload(
        {
            "type": "event_callback",
            "event_id": "Ev2",
            "team_id": "T1",
            "event": {
                "type": "message",
                "subtype": "message_changed",
                "channel": "D1",
                "user": "U1",
                "ts": "1.0",
            },
        }
    )
    assert messages == []


def test_parse_app_uninstalled_lifecycle() -> None:
    messages, life = parse_slack_payload(
        {
            "type": "event_callback",
            "event_id": "EvUninstall",
            "team_id": "T99",
            "event": {"type": "app_uninstalled"},
        }
    )
    assert messages == []
    assert len(life) == 1
    assert life[0].event_type == "app_uninstalled"
    assert life[0].team_id == "T99"
    assert life[0].event_id == "EvUninstall"


def test_parse_message_with_file() -> None:
    messages, life = parse_slack_payload(
        {
            "type": "event_callback",
            "event_id": "EvMsg",
            "team_id": "T1",
            "event": {
                "type": "message",
                "channel": "D1",
                "user": "U42",
                "text": "receipt",
                "ts": "1699999999.000100",
                "files": [
                    {
                        "id": "F1",
                        "name": "r.pdf",
                        "mimetype": "application/pdf",
                        "url_private": "https://files.slack.com/x",
                        "size": 100,
                    }
                ],
            },
        }
    )
    assert life == []
    assert len(messages) == 1
    assert messages[0].user_id == "U42"
    assert len(messages[0].files) == 1
    assert messages[0].files[0].file_id == "F1"


@pytest.mark.asyncio
async def test_resolve_slack_sender_label_falls_back_to_user_id() -> None:
    """Missing profile email still yields a sender label; ingest is never gated."""
    from app.services.ingest.slack_ingest_service import resolve_slack_sender_label

    with patch(
        "app.services.ingest.slack_ingest_service.users_info",
        new_callable=AsyncMock,
        return_value={"ok": True, "user": {"profile": {"real_name": "No Email"}}},
    ):
        label = await resolve_slack_sender_label(
            access_token="xoxb-test",
            slack_user_id="U_NO_EMAIL",
        )
    assert label == "No Email"


@pytest.mark.asyncio
async def test_resolve_slack_sender_label_prefers_email() -> None:
    from app.services.ingest.slack_ingest_service import resolve_slack_sender_label

    with patch(
        "app.services.ingest.slack_ingest_service.users_info",
        new_callable=AsyncMock,
        return_value={
            "ok": True,
            "user": {"profile": {"email": "a@b.com", "real_name": "A"}},
        },
    ):
        label = await resolve_slack_sender_label(
            access_token="xoxb-test",
            slack_user_id="U1",
        )
    assert label == "a@b.com"


def test_slack_capture_never_forces_team_expenses() -> None:
    from app.schemas.rule_book_config import EmployeeMaster
    from app.services.purchase.team_expense_route_policy import (
        should_force_team_expenses,
        team_expenses_blocked_for_upload,
    )

    class Inv:
        capture_source = "slack"
        email_sender = "codevishnu321@gmail.com"
        slack_connection_id = 1

    employees = [
        EmployeeMaster(
            id="e1",
            name="vishnu",
            role="",
            email="codevishnu321@gmail.com",
        )
    ]
    assert should_force_team_expenses(Inv(), employees) is False
    assert team_expenses_blocked_for_upload(Inv()) is True


@pytest.mark.asyncio
async def test_mime_and_size_helpers() -> None:
    from app.services.ingest.slack_ingest_service import _mime_allowed

    assert _mime_allowed("application/pdf") is True
    assert _mime_allowed("image/png") is True
    assert _mime_allowed("application/zip") is False
    assert _mime_allowed("text/plain") is False
