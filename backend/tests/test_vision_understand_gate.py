"""Unit tests for the vision understandability gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.extraction.document_ai_provider import DocumentAiProvider
from app.services.invoice.vision_understand_gate import (
    MIN_UNDERSTAND_CONFIDENCE,
    evaluate_vision_understand,
)


@pytest.mark.asyncio
async def test_vision_understand_can_understand(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(
        "app.services.invoice.vision_understand_gate.resolve_pdf_page_images",
        lambda *_a, **_k: [b"png"],
    )
    monkeypatch.setattr(
        "app.services.extraction.document_ai_provider.provider_available",
        lambda _p: True,
    )

    async def _probe(**_kwargs):
        return {"can_understand": True, "confidence": 0.9, "reason": "clear text"}

    monkeypatch.setattr(
        "app.services.extraction.document_ai_provider.probe_vision_understand",
        _probe,
    )

    result = await evaluate_vision_understand(
        pdf,
        provider=DocumentAiProvider.GEMINI_VISION,
    )
    assert result.can_understand is True
    assert result.confidence == 0.9
    assert result.fail_closed is False


@pytest.mark.asyncio
async def test_vision_understand_cannot_when_model_says_no(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(
        "app.services.invoice.vision_understand_gate.resolve_pdf_page_images",
        lambda *_a, **_k: [b"png"],
    )
    monkeypatch.setattr(
        "app.services.extraction.document_ai_provider.provider_available",
        lambda _p: True,
    )

    async def _probe(**_kwargs):
        return {"can_understand": False, "confidence": 0.8, "reason": "blurry"}

    monkeypatch.setattr(
        "app.services.extraction.document_ai_provider.probe_vision_understand",
        _probe,
    )

    result = await evaluate_vision_understand(
        pdf,
        provider=DocumentAiProvider.GEMINI_VISION,
    )
    assert result.can_understand is False
    assert result.reason == "blurry"


@pytest.mark.asyncio
async def test_vision_understand_confidence_floor(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(
        "app.services.invoice.vision_understand_gate.resolve_pdf_page_images",
        lambda *_a, **_k: [b"png"],
    )
    monkeypatch.setattr(
        "app.services.extraction.document_ai_provider.provider_available",
        lambda _p: True,
    )

    async def _probe(**_kwargs):
        return {
            "can_understand": True,
            "confidence": max(0.0, MIN_UNDERSTAND_CONFIDENCE - 0.1),
            "reason": "maybe",
        }

    monkeypatch.setattr(
        "app.services.extraction.document_ai_provider.probe_vision_understand",
        _probe,
    )

    result = await evaluate_vision_understand(
        pdf,
        provider=DocumentAiProvider.AZURE_FOUNDRY_VISION,
    )
    assert result.can_understand is False
    assert result.reason == "confidence_below_floor"


@pytest.mark.asyncio
async def test_vision_understand_fail_closed_on_provider_error(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(
        "app.services.invoice.vision_understand_gate.resolve_pdf_page_images",
        lambda *_a, **_k: [b"png"],
    )
    monkeypatch.setattr(
        "app.services.extraction.document_ai_provider.provider_available",
        lambda _p: True,
    )

    async def _probe(**_kwargs):
        raise TimeoutError("boom")

    monkeypatch.setattr(
        "app.services.extraction.document_ai_provider.probe_vision_understand",
        _probe,
    )

    result = await evaluate_vision_understand(
        pdf,
        provider=DocumentAiProvider.GEMINI_VISION,
    )
    assert result.can_understand is False
    assert result.fail_closed is True
    assert result.reason == "provider_error"


@pytest.mark.asyncio
async def test_vision_understand_azure_di_fail_closed(tmp_path) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    result = await evaluate_vision_understand(
        Path(pdf),
        provider=DocumentAiProvider.AZURE_DI,
    )
    assert result.can_understand is False
    assert result.fail_closed is True
    assert result.reason == "vision_provider_not_configured"
