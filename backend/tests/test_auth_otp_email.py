"""Tests for login OTP email delivery."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.services.email_recipient_validation import mask_email_for_log
from app.services.auth_email_service import send_login_otp_email


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _configure_production_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant-id")
    monkeypatch.setenv("AZURE_CLIENT_ID", "client-id")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GRAPH_MAILBOX", "vishnu@highvolt.tech")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_dev_mode_skips_real_send(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    result = await send_login_otp_email(to_email="admin@acme.com", otp="123456")
    assert result.sent is True


@pytest.mark.asyncio
async def test_production_uses_graph_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_production_graph(monkeypatch)

    calls: list[dict[str, str]] = []
    smtp_calls: list[dict[str, str]] = []

    def _fake_graph_mail(**kwargs):
        calls.append(kwargs)
        from app.services.graph_mail_sender import GraphMailResult

        return GraphMailResult(sent=True)

    def _fake_smtp(**kwargs):
        smtp_calls.append(kwargs)
        from app.services.auth_email_service import InviteEmailResult

        return InviteEmailResult(sent=True)

    monkeypatch.setattr(
        "app.services.auth_email_service.send_graph_mail",
        _fake_graph_mail,
    )
    monkeypatch.setattr(
        "app.services.auth_email_service._send_via_smtp",
        _fake_smtp,
    )

    result = await send_login_otp_email(
        to_email="dhiren@highvolt.tech",
        otp="654321",
    )
    assert result.sent is True
    assert len(calls) == 1
    assert calls[0]["to_email"] == "dhiren@highvolt.tech"
    assert smtp_calls == []


@pytest.mark.asyncio
async def test_production_graph_failure_does_not_attempt_localhost_smtp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_production_graph(monkeypatch)

    smtp_calls: list[dict[str, str]] = []

    def _fake_graph_mail(**_kwargs):
        from app.services.graph_mail_sender import GraphMailResult

        return GraphMailResult(sent=False, error="Graph sendMail failed (403).")

    def _fake_smtp(**kwargs):
        smtp_calls.append(kwargs)
        from app.services.auth_email_service import InviteEmailResult

        return InviteEmailResult(sent=True)

    monkeypatch.setattr(
        "app.services.auth_email_service.send_graph_mail",
        _fake_graph_mail,
    )
    monkeypatch.setattr(
        "app.services.auth_email_service._send_via_smtp",
        _fake_smtp,
    )

    result = await send_login_otp_email(
        to_email="user@gmail.com",
        otp="111111",
    )
    assert result.sent is False
    assert result.error == "Graph sendMail failed (403)."
    assert smtp_calls == []


@pytest.mark.asyncio
async def test_production_without_graph_returns_clear_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()

    smtp_calls: list[dict[str, str]] = []

    def _fake_smtp(**kwargs):
        smtp_calls.append(kwargs)
        from app.services.auth_email_service import InviteEmailResult

        return InviteEmailResult(sent=True)

    monkeypatch.setattr(
        "app.services.auth_email_service._send_via_smtp",
        _fake_smtp,
    )

    result = await send_login_otp_email(
        to_email="user@gmail.com",
        otp="111111",
    )
    assert result.sent is False
    assert "Graph" in (result.error or "")
    assert smtp_calls == []


def test_mask_email_for_log() -> None:
    assert mask_email_for_log("dhiren@highvolt.tech") == "d***n@highvolt.tech"
    assert mask_email_for_log("ab@test.com") == "a*@test.com"
