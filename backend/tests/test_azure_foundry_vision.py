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
            "app.services.extraction.azure_foundry_vision_client.resolve_pdf_page_images",
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
            "app.services.extraction.azure_foundry_vision_client.resolve_pdf_page_images",
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


@pytest.mark.asyncio
async def test_extract_fields_enriches_ocr_for_foundry_when_di_enabled(tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    ocr = OcrArtifact(success=True, sparse=False, text="Invoice text", text_length=12)
    enriched = OcrArtifact(
        success=True,
        sparse=False,
        text="Invoice text",
        text_length=12,
        payload_json={"invoice_fields": {"vendor": "Acme"}},
    )
    expected = LlmDocumentResult(suggested_dt="DT-01", confidence=0.9)

    monkeypatch.setattr(
        "app.services.extraction.document_ai_provider.is_di_enabled",
        lambda: True,
    )

    with (
        patch(
            "app.services.extraction.document_ai_provider.enrich_ocr_for_route",
            return_value=(enriched, {"route": "invoice"}),
        ) as mock_enrich,
        patch(
            "app.services.extraction.document_ai_provider.extract_fields_azure_foundry",
            new=AsyncMock(return_value=expected),
        ) as mock_extract,
    ):
        result = await extract_fields(
            ocr,
            file_path=pdf_path,
            org=OrgContext(),
            document_types=[],
            confirmed_dt="DT-01",
            few_shots=None,
            provider=DocumentAiProvider.AZURE_FOUNDRY_VISION,
        )

    mock_enrich.assert_called_once()
    mock_extract.assert_awaited_once()
    assert mock_extract.await_args is not None
    assert mock_extract.await_args.args[0] is enriched
    assert result.ocr is enriched
    assert result.di_enrich_detail == {"route": "invoice"}


@pytest.mark.asyncio
async def test_extract_fields_forwards_force_invoice_model(tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    ocr = OcrArtifact(success=True, sparse=False, text="Invoice text", text_length=12)
    expected = LlmDocumentResult(suggested_dt="DT-01", confidence=0.9)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "app.services.extraction.document_ai_provider.is_di_enabled",
        lambda: True,
    )

    def _enrich(*_args, **kwargs):
        captured.update(kwargs)
        return ocr, {"forced": True}

    with (
        patch(
            "app.services.extraction.document_ai_provider.enrich_ocr_for_route",
            _enrich,
        ),
        patch(
            "app.services.extraction.document_ai_provider.extract_fields_claude",
            new=AsyncMock(return_value=expected),
        ),
    ):
        await extract_fields(
            ocr,
            file_path=pdf_path,
            org=OrgContext(),
            document_types=[],
            confirmed_dt="DT-01",
            few_shots=None,
            provider=DocumentAiProvider.CLAUDE_VISION,
            force_invoice_model=True,
        )

    assert captured.get("force_invoice_model") is True


@pytest.mark.asyncio
async def test_vision_json_waits_open_circuit_then_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.extraction import azure_foundry_vision_client as client

    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": '{"ok": true}'}}]}

    class _Http:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return _Resp()

    class _Slot:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(client, "get_settings", lambda: type(
        "S",
        (),
        {
            "azure_foundry_vision_configured": True,
            "azure_ai_foundry_endpoint": "https://example.openai.azure.com/",
            "azure_ai_foundry_deployment": "gpt-4o",
            "azure_ai_foundry_api_version": "2024-08-01-preview",
            "azure_ai_foundry_api_key": "test-key",
            "azure_openai_cooldown_seconds": 45.0,
            "runtime_llm_max_retries": 1,
        },
    )())
    with (
        patch(
            "app.services.extraction.azure_openai_throttle.azure_openai_cooling_down",
            side_effect=[True, False],
        ),
        patch(
            "app.services.extraction.azure_openai_throttle.azure_openai_cooldown_remaining_seconds",
            return_value=2.5,
        ),
        patch(
            "app.services.extraction.azure_openai_throttle.azure_openai_slot_async",
            return_value=_Slot(),
        ),
        patch("httpx.AsyncClient", return_value=_Http()),
        patch("asyncio.sleep", new=_fake_sleep),
        patch(
            "app.services.extraction.azure_openai_throttle.note_azure_openai_success",
        ),
    ):
        result = await client._vision_json(
            system="sys",
            user_text="{}",
            images=[b"img"],
            timeout_seconds=10,
        )

    assert result == {"ok": True}
    assert sleeps and sleeps[0] == 2.5


@pytest.mark.asyncio
async def test_foundry_read_falls_back_to_di_on_empty(tmp_path) -> None:
    from app.services.extraction.document_ai_provider import read_for_classification

    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    di_ocr = OcrArtifact(success=True, text="from di", text_length=7)

    with (
        patch(
            "app.services.extraction.document_ai_provider.read_for_classification_azure_foundry",
            new=AsyncMock(side_effect=ValueError("azure_foundry_read_failed")),
        ),
        patch(
            "app.services.extraction.document_ai_provider.is_di_enabled",
            return_value=True,
        ),
        patch(
            "app.services.extraction.document_ai_provider.read_layout_for_classification",
            return_value=di_ocr,
        ) as mock_di,
    ):
        result = await read_for_classification(
            pdf_path,
            provider=DocumentAiProvider.AZURE_FOUNDRY_VISION,
            org=OrgContext(),
            document_types=[],
        )

    mock_di.assert_called_once()
    assert result is di_ocr
    assert result.text == "from di"
