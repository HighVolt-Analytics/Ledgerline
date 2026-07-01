"""Graph mail sender tests."""

from datetime import datetime, timezone

import pytest

from app.config import get_settings
from app.services.graph_mail_sender import graph_mail_send_configured, send_graph_mail
from app.services.mailbox_invite_service import send_invite_email


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant-id")
    monkeypatch.setenv("AZURE_CLIENT_ID", "client-id")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GRAPH_MAILBOX", "sender@example.com")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_graph_mail_send_configured_when_mailbox_set() -> None:
    assert graph_mail_send_configured() is True


def test_send_invite_email_uses_graph_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, str]] = []

    def _fake_send_graph_mail(**kwargs):
        calls.append(kwargs)
        from app.services.graph_mail_sender import GraphMailResult

        return GraphMailResult(sent=True)

    monkeypatch.setattr(
        "app.services.mailbox_invite_service.send_graph_mail",
        _fake_send_graph_mail,
    )

    result = send_invite_email(
        to_email="owner@gmail.com",
        tenant_name="Acme",
        requested_email="owner@gmail.com",
        connect_url="http://localhost:5173/connect-mailbox?token=abc",
        personal_message="Please connect",
        expires_at=datetime.now(timezone.utc),
    )
    assert result.sent is True
    assert len(calls) == 1
    assert calls[0]["to_email"] == "owner@gmail.com"
    assert "Connect my mailbox" in calls[0]["body_html"]


def test_send_graph_mail_returns_error_without_mailbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GRAPH_MAILBOX", "")
    get_settings.cache_clear()
    result = send_graph_mail(
        to_email="owner@example.com",
        subject="Test",
        body_text="Hi",
        body_html="<p>Hi</p>",
    )
    assert result.sent is False
    assert result.error
