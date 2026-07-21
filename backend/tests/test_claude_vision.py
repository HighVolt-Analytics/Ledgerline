"""Claude on Azure AI Foundry vision provider wiring."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import get_settings
from app.services.extraction.claude_vision_client import _messages_url, _parse_json_text
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


def test_parse_json_text_handles_fences() -> None:
    assert _parse_json_text('{"can_understand": true}') == {"can_understand": True}
    assert _parse_json_text('```json\n{"a": 1}\n```') == {"a": 1}


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
    response.json.return_value = {
        "content": [{"type": "text", "text": json.dumps({"can_understand": True, "confidence": 0.8})}]
    }

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=response)

    with patch("app.services.extraction.claude_vision_client.httpx.AsyncClient", return_value=mock_client):
        result = await client._vision_json(
            system="return json",
            user_text='{"task":"vision_understand"}',
            images=[b"\x89PNG\r\n\x1a\n" + b"\x00" * 32],
            timeout_seconds=30,
        )

    assert result == {"can_understand": True, "confidence": 0.8}
    call_kwargs = mock_client.post.await_args
    assert call_kwargs.args[0].endswith("/anthropic/v1/messages")
    assert call_kwargs.kwargs["headers"]["api-key"] == "test-key"
    assert call_kwargs.kwargs["headers"]["x-api-key"] == "test-key"
    assert call_kwargs.kwargs["headers"]["anthropic-version"] == "2023-06-01"
    body = call_kwargs.kwargs["json"]
    assert body["model"] == "claude-sonnet-4-6"
    assert body["messages"][0]["content"][0]["type"] == "image"
    get_settings.cache_clear()
