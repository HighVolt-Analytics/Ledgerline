"""Azure OpenAI client retry policy + 429 circuit breaker."""

from __future__ import annotations

import httpx
import pytest

from app.services.extraction import azure_openai_client as client
from app.services.extraction import azure_openai_throttle as throttle


@pytest.fixture(autouse=True)
def _reset_circuit() -> None:
    throttle.note_azure_openai_success(scope="chat")
    throttle.note_azure_openai_success(scope="vision")
    yield
    throttle.note_azure_openai_success(scope="chat")
    throttle.note_azure_openai_success(scope="vision")


def test_runtime_read_timeout_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def _fail_once(**_kwargs):
        calls["count"] += 1
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(client, "_chat_json_once", _fail_once)
    monkeypatch.setattr(
        client,
        "get_settings",
        lambda: type(
            "S",
            (),
            {
                "runtime_llm_available": True,
                "azure_openai_chat_deployment": "gpt-4o",
                "runtime_llm_timeout_seconds": 45,
                "runtime_llm_max_retries": 2,
            },
        )(),
    )

    result = client.chat_json(system="s", user="u", require_runtime=True)

    assert result is None
    assert calls["count"] == 1


def test_sample_proposal_retries_read_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def _fail_once_then_ok(**_kwargs):
        calls["count"] += 1
        if calls["count"] < 2:
            raise httpx.ReadTimeout("timed out")
        return {}

    monkeypatch.setattr(client, "_chat_json_once", _fail_once_then_ok)
    monkeypatch.setattr(client, "is_azure_openai_enabled", lambda: True)
    monkeypatch.setattr(
        client,
        "get_settings",
        lambda: type(
            "S",
            (),
            {
                "azure_openai_chat_deployment": "gpt-4o",
                "sample_proposal_llm_timeout_seconds": 30,
            },
        )(),
    )

    result = client.chat_json(system="s", user="u", require_runtime=False)

    assert result == {}
    assert calls["count"] == 2


def test_runtime_429_fails_fast_and_opens_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def _always_429(**_kwargs):
        calls["count"] += 1
        request = httpx.Request("POST", "https://example.test/chat")
        response = httpx.Response(429, request=request, headers={"Retry-After": "20"})
        raise httpx.HTTPStatusError("rate limited", request=request, response=response)

    monkeypatch.setattr(client, "_chat_json_once", _always_429)
    monkeypatch.setattr(
        client,
        "get_settings",
        lambda: type(
            "S",
            (),
            {
                "runtime_llm_available": True,
                "azure_openai_chat_deployment": "gpt-4o",
                "runtime_llm_timeout_seconds": 45,
                "runtime_llm_max_retries": 4,
                "azure_openai_cooldown_seconds": 60.0,
            },
        )(),
    )
    monkeypatch.setattr(
        throttle,
        "get_settings",
        lambda: type("S", (), {"azure_openai_cooldown_seconds": 60.0})(),
    )

    assert client.chat_json(system="s", user="u", require_runtime=True) is None
    assert calls["count"] == 1
    assert throttle.azure_openai_cooling_down() is True

    # Second call must not hit Azure while circuit is open.
    assert client.chat_json(system="s", user="u", require_runtime=True) is None
    assert calls["count"] == 1


def test_retry_sleep_honours_retry_after_ms() -> None:
    request = httpx.Request("POST", "https://example.test/chat")
    response = httpx.Response(429, request=request, headers={"retry-after-ms": "15000"})
    exc = httpx.HTTPStatusError("rate limited", request=request, response=response)
    assert client._retry_sleep_seconds(exc, 0) == 15.0


def test_retry_sleep_429_has_firm_floor() -> None:
    request = httpx.Request("POST", "https://example.test/chat")
    response = httpx.Response(429, request=request)
    exc = httpx.HTTPStatusError("rate limited", request=request, response=response)
    assert client._retry_sleep_seconds(exc, 0) >= 8.0
