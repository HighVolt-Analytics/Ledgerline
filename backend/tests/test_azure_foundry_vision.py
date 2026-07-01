"""Azure AI Foundry vision provider wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.config import get_settings
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.services.document_ai_provider import DocumentAiProvider, classify_only, provider_available


def test_document_ai_provider_from_config_accepts_foundry_aliases() -> None:
    assert DocumentAiProvider.from_config("azure_foundry") == DocumentAiProvider.AZURE_FOUNDRY_VISION
    assert DocumentAiProvider.from_config("azure_foundry_vision") == DocumentAiProvider.AZURE_FOUNDRY_VISION


def test_default_document_ai_provider_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISION_LLM_PROVIDER", "azure_foundry")
    get_settings.cache_clear()
    assert get_settings().default_document_ai_provider == "azure_foundry_vision"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_foundry_classify_only_routes_to_client() -> None:
    ocr = OcrArtifact(success=True, text="Purchase Order", text_length=14)
    expected = LlmDocumentResult(suggested_dt="DT-02", confidence=0.92)

    with patch(
        "app.services.document_ai_provider.is_azure_foundry_vision_available",
        return_value=True,
    ):
        assert provider_available(DocumentAiProvider.AZURE_FOUNDRY_VISION) is True

    with patch(
        "app.services.document_ai_provider.classify_only_azure_foundry",
        new=AsyncMock(return_value=expected),
    ) as mock_classify:
        result = await classify_only(
            ocr,
            file_path="sample.pdf",
            org=AsyncMock(),
            document_types=[],
            few_shots=None,
            provider=DocumentAiProvider.AZURE_FOUNDRY_VISION,
        )

    assert result == expected
    mock_classify.assert_awaited_once()
