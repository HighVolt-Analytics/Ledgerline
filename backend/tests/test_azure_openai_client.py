"""Azure OpenAI client retry policy."""

from __future__ import annotations

import httpx
import pytest

from app.services.extraction import azure_openai_client as client


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

    def _fail_twice(**_kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise httpx.ReadTimeout("timed out")
        return {}

    monkeypatch.setattr(client, "_chat_json_once", _fail_twice)
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
    assert calls["count"] == 3


def test_runtime_retries_429_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    calls = {"count": 0}

    def _fail_once(**_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            request = httpx.Request("POST", "https://example.test/chat")
            response = httpx.Response(429, request=request, headers={"Retry-After": "0"})
            raise httpx.HTTPStatusError("rate limited", request=request, response=response)
        return {}

    monkeypatch.setattr(client, "_chat_json_once", _fail_once)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
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
                "runtime_llm_max_retries": 0,
            },
        )(),
    )

    result = client.chat_json(system="s", user="u", require_runtime=True)

    assert result == {}
    assert calls["count"] == 2
