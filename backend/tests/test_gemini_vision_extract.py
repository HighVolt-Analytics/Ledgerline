"""Gemini vision OCR-first extract."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.gemini_vision_client import extract_fields_gemini
from app.services.tenant.tenant_org_context import OrgContext


@pytest.mark.asyncio
async def test_gemini_extract_ocr_first_skips_images_when_not_sparse(tmp_path) -> None:
    ocr = OcrArtifact(
        success=True,
        sparse=False,
        text="Tax Invoice\nVendor: Acme Pty Ltd\nTotal: 110.00",
        text_length=42,
        layout_kv={"Invoice No": "INV-1"},
    )
    captured: dict[str, object] = {}

    async def _fake_generate(*, system: str, user_parts, timeout_seconds: int):
        captured["system"] = system
        captured["user_parts"] = user_parts
        assert len(user_parts) == 1
        assert "inlineData" not in str(user_parts)
        payload = json.loads(user_parts[0]["text"])
        assert payload["ocr"]["text_excerpt"].startswith("Tax Invoice")
        return {
            "suggested_dt": "DT-01",
            "confidence": 0.9,
            "vendor": "Acme Pty Ltd",
            "total": 110.0,
            "line_items": [],
            "field_confidence": {},
        }

    with patch(
        "app.services.extraction.gemini_vision_client._generate_json",
        new=AsyncMock(side_effect=_fake_generate),
    ):
        with patch(
            "app.services.extraction.gemini_vision_client.resolve_pdf_page_images",
        ) as mock_pages:
            result = await extract_fields_gemini(
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
async def test_gemini_extract_sparse_attaches_images(tmp_path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    ocr = OcrArtifact(success=True, sparse=True, text="blur", text_length=4)

    async def _fake_generate(*, system: str, user_parts, timeout_seconds: int):
        assert "Sparse OCR" in system
        assert any("inlineData" in part for part in user_parts if isinstance(part, dict))
        return {
            "suggested_dt": "DT-01",
            "confidence": 0.8,
            "vendor": "Acme",
            "line_items": [],
            "field_confidence": {},
        }

    with patch(
        "app.services.extraction.gemini_vision_client._generate_json",
        new=AsyncMock(side_effect=_fake_generate),
    ):
        with patch(
            "app.services.extraction.gemini_vision_client.resolve_pdf_page_images",
            return_value=[b"page1"],
        ) as mock_pages:
            result = await extract_fields_gemini(
                ocr,
                pdf_path,
                org=OrgContext(),
                document_types=[],
                confirmed_dt="DT-01",
            )

    mock_pages.assert_called_once()
    assert result is not None
