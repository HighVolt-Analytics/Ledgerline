"""Azure AI Foundry vision provider wiring."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.config import get_settings
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.document_ai_provider import (
    DocumentAiProvider,
    classify_only,
    extract_fields,
    provider_available,
)
from app.services.tenant.tenant_org_context import OrgContext


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
        "app.services.extraction.document_ai_provider.is_azure_foundry_vision_available",
        return_value=True,
    ):
        assert provider_available(DocumentAiProvider.AZURE_FOUNDRY_VISION) is True

    with patch(
        "app.services.extraction.document_ai_provider.classify_only_azure_foundry",
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


@pytest.mark.asyncio
async def test_foundry_extract_ocr_first_skips_images_when_not_sparse(tmp_path) -> None:
    from app.services.extraction.azure_foundry_vision_client import extract_fields_azure_foundry

    ocr = OcrArtifact(
        success=True,
        sparse=False,
        text="Tax Invoice\nVendor: Acme Pty Ltd\nTotal: 110.00",
        text_length=42,
        layout_kv={"Invoice No": "INV-1"},
    )
    captured: dict[str, object] = {}

    async def _fake_vision(*, system: str, user_text: str, images: list[bytes], timeout_seconds: int):
        captured["system"] = system
        captured["user_text"] = user_text
        captured["images"] = images
        assert "structure" in system.lower() or "ocr" in system.lower()
        assert images == []
        payload = json.loads(user_text)
        assert payload["ocr"]["text_excerpt"].startswith("Tax Invoice")
        assert payload["ocr"]["layout_kv"] == {"Invoice No": "INV-1"}
        return {
            "suggested_dt": "DT-01",
            "confidence": 0.9,
            "vendor": "Acme Pty Ltd",
            "total": 110.0,
            "line_items": [],
            "field_confidence": {},
        }

    with patch(
        "app.services.extraction.azure_foundry_vision_client._vision_json",
        new=AsyncMock(side_effect=_fake_vision),
    ):
        with patch(
            "app.services.extraction.azure_foundry_vision_client.pdf_page_images",
        ) as mock_pages:
            result = await extract_fields_azure_foundry(
                ocr,
                tmp_path / "doc.pdf",
                org=OrgContext(),
                document_types=[],
                confirmed_dt="DT-01",
            )

    mock_pages.assert_not_called()
    assert result is not None
    assert result.suggested_dt == "DT-01"


@pytest.mark.asyncio
async def test_foundry_extract_sparse_attaches_images(tmp_path) -> None:
    from app.services.extraction.azure_foundry_vision_client import extract_fields_azure_foundry

    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    ocr = OcrArtifact(success=True, sparse=True, text="blur", text_length=4)
    captured: dict[str, object] = {}

    async def _fake_vision(*, system: str, user_text: str, images: list[bytes], timeout_seconds: int):
        captured["images"] = images
        captured["system"] = system
        assert len(images) == 1
        assert "Sparse OCR" in system
        return {
            "suggested_dt": "DT-01",
            "confidence": 0.8,
            "vendor": "Acme",
            "line_items": [],
            "field_confidence": {},
        }

    with patch(
        "app.services.extraction.azure_foundry_vision_client._vision_json",
        new=AsyncMock(side_effect=_fake_vision),
    ):
        with patch(
            "app.services.extraction.azure_foundry_vision_client.pdf_page_images",
            return_value=[b"page1"],
        ) as mock_pages:
            result = await extract_fields_azure_foundry(
                ocr,
                pdf_path,
                org=OrgContext(),
                document_types=[],
                confirmed_dt="DT-01",
            )

    mock_pages.assert_called_once()
    assert result is not None


@pytest.mark.asyncio
async def test_extract_fields_provider_passes_ocr_to_foundry(tmp_path) -> None:
    ocr = OcrArtifact(success=True, sparse=False, text="Invoice text", text_length=12)
    expected = LlmDocumentResult(suggested_dt="DT-01", confidence=0.9)

    with patch(
        "app.services.extraction.document_ai_provider.extract_fields_azure_foundry",
        new=AsyncMock(return_value=expected),
    ) as mock_extract:
        result = await extract_fields(
            ocr,
            file_path=tmp_path / "doc.pdf",
            org=OrgContext(),
            document_types=[],
            confirmed_dt="DT-01",
            few_shots=None,
            provider=DocumentAiProvider.AZURE_FOUNDRY_VISION,
        )

    assert result.llm == expected
    mock_extract.assert_awaited_once()
    call_kwargs = mock_extract.await_args
    assert call_kwargs is not None
    assert call_kwargs.args[0] is ocr
