"""Claude on Azure AI Foundry vision provider wiring."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.config import get_settings
from app.services.extraction.claude_vision_client import (
    _messages_url,
    _parse_json_text,
    _response_text,
)
from app.services.extraction.document_ai_provider import (
    DocumentAiProvider,
    provider_available,
    provider_unavailable_reason,
)


def test_document_ai_provider_from_config_accepts_claude_aliases() -> None:
    assert DocumentAiProvider.from_config("claude") == DocumentAiProvider.CLAUDE_VISION
    assert DocumentAiProvider.from_config("claude_vision") == DocumentAiProvider.CLAUDE_VISION
    assert DocumentAiProvider.from_config("azure_claude") == DocumentAiProvider.CLAUDE_VISION


def test_default_document_ai_provider_claude_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISION_LLM_PROVIDER", "claude_vision")
    get_settings.cache_clear()
    assert get_settings().default_document_ai_provider == "claude_vision"
    get_settings.cache_clear()


def test_messages_url_appends_anthropic_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "AZURE_AI_VISUALIZATION_ENDPOINT",
        "https://eastus2.api.cognitive.microsoft.com",
    )
    monkeypatch.setenv("AZURE_AI_VISUALIZATION_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_AI_VISUALIZATION_DEPLOYMENT_NAME", "claude-sonnet-4-6")
    get_settings.cache_clear()
    assert (
        _messages_url()
        == "https://eastus2.api.cognitive.microsoft.com/anthropic/v1/messages"
    )
    get_settings.cache_clear()


def test_parse_json_text_handles_fences_and_trailing() -> None:
    assert _parse_json_text('{"can_understand": true}') == {"can_understand": True}
    assert _parse_json_text('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json_text('Here you go:\n{"b": 2}\nThanks') == {"b": 2}
    assert _response_text(
        {"content": [{"type": "text", "text": '```json\n{"can_understand": true}\n```'}]}
    ) == '```json\n{"can_understand": true}\n```'
    assert _parse_json_text(
        _response_text(
            {"content": [{"type": "text", "text": '```json\n{"can_understand": true, "confidence": 0.9}\n```'}]}
        )
    ) == {"can_understand": True, "confidence": 0.9}


@pytest.mark.asyncio
async def test_probe_understand_routes_to_claude() -> None:
    from app.services.extraction.document_ai_provider import probe_vision_understand

    with patch(
        "app.services.extraction.document_ai_provider.is_claude_vision_available",
        return_value=True,
    ):
        assert provider_available(DocumentAiProvider.CLAUDE_VISION) is True

    with patch(
        "app.services.extraction.document_ai_provider.probe_understand_claude",
        new=AsyncMock(return_value={"can_understand": True, "confidence": 0.9}),
    ) as mock_probe:
        raw = await probe_vision_understand(
            provider=DocumentAiProvider.CLAUDE_VISION,
            images=[b"fake"],
        )
        assert raw == {"can_understand": True, "confidence": 0.9}
        mock_probe.assert_awaited_once()


@pytest.mark.asyncio
async def test_extract_header_routes_to_claude() -> None:
    from app.services.extraction.document_ai_provider import extract_vision_header
    from app.services.tenant.tenant_org_context import OrgContext

    org = OrgContext(
        legal_name="Acme",
        abn="123",
        aliases=[],
        default_perspective="buyer",
        intake_summary="",
    )
    with patch(
        "app.services.extraction.document_ai_provider.extract_header_claude",
        new=AsyncMock(return_value={"document_heading": "TAX INVOICE"}),
    ) as mock_header:
        raw = await extract_vision_header(
            provider=DocumentAiProvider.CLAUDE_VISION,
            images=[b"fake"],
            org=org,
        )
        assert raw == {"document_heading": "TAX INVOICE"}
        mock_header.assert_awaited_once()


def test_claude_unavailable_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_AI_VISUALIZATION_ENDPOINT", "")
    monkeypatch.setenv("AZURE_AI_VISUALIZATION_API_KEY", "")
    monkeypatch.setenv("AZURE_AI_VISUALIZATION_DEPLOYMENT_NAME", "")
    get_settings.cache_clear()
    assert "AZURE_AI_VISUALIZATION_" in provider_unavailable_reason(
        DocumentAiProvider.CLAUDE_VISION
    )
    get_settings.cache_clear()


def _mock_async_client(post_side_effect) -> MagicMock:
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=post_side_effect)
    return mock_client


@pytest.mark.asyncio
async def test_claude_vision_json_posts_messages_api(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.extraction import claude_vision_client as client

    monkeypatch.setenv(
        "AZURE_AI_VISUALIZATION_ENDPOINT",
        "https://eastus2.api.cognitive.microsoft.com",
    )
    monkeypatch.setenv("AZURE_AI_VISUALIZATION_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_AI_VISUALIZATION_DEPLOYMENT_NAME", "claude-sonnet-4-6")
    get_settings.cache_clear()

    response = MagicMock()
    response.raise_for_status = MagicMock()
    # Azure Claude often wraps JSON in markdown fences
    response.json.return_value = {
        "content": [
            {
                "type": "text",
                "text": '```json\n{"can_understand": true, "confidence": 0.8, "reason": "ok"}\n```',
            }
        ]
    }

    mock_client = _mock_async_client([response])

    with (
        patch("app.services.extraction.claude_vision_client.httpx.AsyncClient", return_value=mock_client),
        patch(
            "app.services.extraction.azure_openai_throttle.azure_openai_slot_async",
        ) as slot,
        patch(
            "app.services.extraction.azure_openai_throttle.azure_openai_cooling_down",
            return_value=False,
        ),
        patch(
            "app.services.extraction.azure_openai_throttle.note_azure_openai_success",
        ) as note_ok,
    ):
        slot.return_value.__aenter__ = AsyncMock(return_value=None)
        slot.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await client._vision_json(
            system="return json",
            user_text='{"task":"vision_understand"}',
            images=[b"\x89PNG\r\n\x1a\n" + b"\x00" * 32],
            timeout_seconds=30,
        )

    assert result == {"can_understand": True, "confidence": 0.8, "reason": "ok"}
    call_kwargs = mock_client.post.await_args
    assert call_kwargs.args[0].endswith("/anthropic/v1/messages")
    assert call_kwargs.kwargs["headers"]["api-key"] == "test-key"
    assert call_kwargs.kwargs["headers"]["x-api-key"] == "test-key"
    body = call_kwargs.kwargs["json"]
    assert body["model"] == "claude-sonnet-4-6"
    assert body["temperature"] == 0.0
    assert body["messages"][0]["content"][0]["type"] == "image"
    # Azure Claude rejects assistant prefill — conversation must end on user.
    assert body["messages"][-1]["role"] == "user"
    assert all(m["role"] != "assistant" for m in body["messages"])
    note_ok.assert_called()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_claude_vision_retries_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.extraction import claude_vision_client as client

    monkeypatch.setenv(
        "AZURE_AI_VISUALIZATION_ENDPOINT",
        "https://eastus2.api.cognitive.microsoft.com",
    )
    monkeypatch.setenv("AZURE_AI_VISUALIZATION_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_AI_VISUALIZATION_DEPLOYMENT_NAME", "claude-sonnet-4-6")
    monkeypatch.setenv("RUNTIME_LLM_MAX_RETRIES", "2")
    get_settings.cache_clear()

    req = httpx.Request("POST", "https://eastus2.api.cognitive.microsoft.com/anthropic/v1/messages")
    resp_429 = httpx.Response(429, request=req, headers={"Retry-After": "0"})
    ok = MagicMock()
    ok.raise_for_status = MagicMock()
    ok.json.return_value = {
        "content": [{"type": "text", "text": json.dumps({"can_understand": True, "confidence": 0.7})}]
    }

    mock_client = _mock_async_client(
        [
            httpx.HTTPStatusError("rate limited", request=req, response=resp_429),
            ok,
        ]
    )

    with (
        patch("app.services.extraction.claude_vision_client.httpx.AsyncClient", return_value=mock_client),
        patch("app.services.extraction.claude_vision_client.asyncio.sleep", new=AsyncMock()),
        patch(
            "app.services.extraction.azure_openai_throttle.azure_openai_slot_async",
        ) as slot,
        patch(
            "app.services.extraction.azure_openai_throttle.azure_openai_cooling_down",
            return_value=False,
        ),
        patch(
            "app.services.extraction.azure_openai_throttle.note_azure_openai_rate_limited",
        ) as note_429,
        patch(
            "app.services.extraction.azure_openai_throttle.note_azure_openai_success",
        ),
    ):
        slot.return_value.__aenter__ = AsyncMock(return_value=None)
        slot.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await client._vision_json(
            system="return json",
            user_text='{"task":"vision_understand"}',
            images=[b"\x89PNG\r\n\x1a\n" + b"\x00" * 32],
            timeout_seconds=30,
        )

    assert result == {"can_understand": True, "confidence": 0.7}
    assert mock_client.post.await_count == 2
    note_429.assert_called()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_claude_vision_repairs_invalid_json_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.extraction import claude_vision_client as client

    monkeypatch.setenv(
        "AZURE_AI_VISUALIZATION_ENDPOINT",
        "https://eastus2.api.cognitive.microsoft.com",
    )
    monkeypatch.setenv("AZURE_AI_VISUALIZATION_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_AI_VISUALIZATION_DEPLOYMENT_NAME", "claude-sonnet-4-6")
    get_settings.cache_clear()

    bad = MagicMock()
    bad.raise_for_status = MagicMock()
    bad.json.return_value = {
        "content": [{"type": "text", "text": "I cannot return JSON right now."}]
    }
    good = MagicMock()
    good.raise_for_status = MagicMock()
    good.json.return_value = {
        "content": [
            {
                "type": "text",
                "text": '```json\n{"document_heading": "TAX INVOICE", "confidence": 0.9}\n```',
            }
        ]
    }

    mock_client = _mock_async_client([bad, good])

    with (
        patch("app.services.extraction.claude_vision_client.httpx.AsyncClient", return_value=mock_client),
        patch("app.services.extraction.claude_vision_client.asyncio.sleep", new=AsyncMock()),
        patch(
            "app.services.extraction.azure_openai_throttle.azure_openai_slot_async",
        ) as slot,
        patch(
            "app.services.extraction.azure_openai_throttle.azure_openai_cooling_down",
            return_value=False,
        ),
        patch(
            "app.services.extraction.azure_openai_throttle.note_azure_openai_success",
        ),
    ):
        slot.return_value.__aenter__ = AsyncMock(return_value=None)
        slot.return_value.__aexit__ = AsyncMock(return_value=None)
        result = await client._vision_json(
            system="return json",
            user_text='{"task":"vision_header_extract"}',
            images=[b"\x89PNG\r\n\x1a\n" + b"\x00" * 32],
            timeout_seconds=30,
        )

    assert result == {"document_heading": "TAX INVOICE", "confidence": 0.9}
    assert mock_client.post.await_count == 2
    get_settings.cache_clear()
