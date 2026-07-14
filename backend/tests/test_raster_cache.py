"""Per-invoice raster image cache across vision phases."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.vision_pdf import resolve_pdf_page_images
from app.services.tenant.tenant_org_context import OrgContext


def test_resolve_pdf_page_images_populates_cache(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    cache: list[bytes] = []
    fake_pages = [b"page-a", b"page-b"]

    with patch(
        "app.services.extraction.vision_pdf.pdf_page_images",
        return_value=fake_pages,
    ) as mock_raster:
        first = resolve_pdf_page_images(pdf_path, cache)
        second = resolve_pdf_page_images(pdf_path, cache)

    mock_raster.assert_called_once()
    assert first is cache
    assert second is cache
    assert cache == fake_pages


def test_resolve_pdf_page_images_none_cache_rasterizes_each_call(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    with patch(
        "app.services.extraction.vision_pdf.pdf_page_images",
        side_effect=[[b"page"], [b"page"]],
    ) as mock_raster:
        first = resolve_pdf_page_images(pdf_path, None)
        second = resolve_pdf_page_images(pdf_path, None)

    assert mock_raster.call_count == 2
    assert first == [b"page"]
    assert second == [b"page"]
    assert first is not second


def test_resolve_pdf_page_images_no_cross_invoice_leak(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    cache_a: list[bytes] = []
    cache_b: list[bytes] = []

    with patch(
        "app.services.extraction.vision_pdf.pdf_page_images",
        side_effect=[[b"invoice-a"], [b"invoice-b"]],
    ) as mock_raster:
        resolve_pdf_page_images(pdf_path, cache_a)
        resolve_pdf_page_images(pdf_path, cache_b)

    assert mock_raster.call_count == 2
    assert cache_a == [b"invoice-a"]
    assert cache_b == [b"invoice-b"]


@pytest.mark.asyncio
async def test_foundry_shared_cache_single_rasterize(tmp_path: Path) -> None:
    from app.services.extraction.azure_foundry_vision_client import (
        classify_only_azure_foundry,
        extract_fields_azure_foundry,
        read_for_classification_azure_foundry,
    )

    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    cache: list[bytes] = []
    fake_pages = [b"png-page-1"]

    async def _fake_vision(*, system: str, user_text: str, images: list[bytes], timeout_seconds: int):
        return {
            "document_heading": "Tax Invoice",
            "text_excerpt": "Tax Invoice vendor total",
            "suggested_dt": "DT-01",
            "confidence": 0.9,
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
            side_effect=lambda path, cache=None: resolve_pdf_page_images(path, cache),
        ) as mock_resolve:
            with patch(
                "app.services.extraction.vision_pdf.pdf_page_images",
                return_value=fake_pages,
            ) as mock_raster:
                await read_for_classification_azure_foundry(
                    pdf_path,
                    org=OrgContext(),
                    document_types=[],
                    vision_page_images=cache,
                )
                ocr = OcrArtifact(
                    success=True,
                    sparse=True,
                    text="blur",
                    text_length=4,
                    payload_json={"document_heading": "Tax Invoice"},
                )
                await classify_only_azure_foundry(
                    pdf_path,
                    ocr,
                    org=OrgContext(),
                    document_types=[],
                    vision_page_images=cache,
                )
                await extract_fields_azure_foundry(
                    ocr,
                    pdf_path,
                    org=OrgContext(),
                    document_types=[],
                    confirmed_dt="DT-01",
                    vision_page_images=cache,
                )

    assert mock_raster.call_count == 1
    assert mock_resolve.call_count == 3
    assert cache == fake_pages


@pytest.mark.asyncio
async def test_foundry_shared_cache_byte_identity(tmp_path: Path) -> None:
    from app.services.extraction.azure_foundry_vision_client import (
        classify_only_azure_foundry,
        read_for_classification_azure_foundry,
    )

    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    cache: list[bytes] = []
    fake_pages = [b"identical-png"]
    seen_images: list[list[bytes]] = []

    async def _fake_vision(*, system: str, user_text: str, images: list[bytes], timeout_seconds: int):
        seen_images.append(list(images))
        return {
            "document_heading": "Invoice",
            "text_excerpt": "Invoice body text here",
            "suggested_dt": "DT-01",
            "confidence": 0.9,
        }

    with patch(
        "app.services.extraction.azure_foundry_vision_client._vision_json",
        new=AsyncMock(side_effect=_fake_vision),
    ):
        with patch(
            "app.services.extraction.vision_pdf.pdf_page_images",
            return_value=fake_pages,
        ):
            await read_for_classification_azure_foundry(
                pdf_path,
                org=OrgContext(),
                document_types=[],
                vision_page_images=cache,
            )
            ocr = OcrArtifact(
                success=True,
                sparse=False,
                text="Invoice body text here",
                text_length=22,
                payload_json={"document_heading": "Invoice"},
            )
            await classify_only_azure_foundry(
                pdf_path,
                ocr,
                org=OrgContext(),
                document_types=[],
                vision_page_images=cache,
            )

    assert len(seen_images) == 2
    assert seen_images[0] == fake_pages
    assert seen_images[1] == fake_pages
    assert seen_images[0][0] is seen_images[1][0]


@pytest.mark.asyncio
async def test_foundry_policy_reextract_reuses_cache_on_sparse_flip(tmp_path: Path) -> None:
    from app.services.extraction.azure_foundry_vision_client import extract_fields_azure_foundry

    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    cache: list[bytes] = [b"cached-page"]
    captured: list[list[bytes]] = []

    async def _fake_vision(*, system: str, user_text: str, images: list[bytes], timeout_seconds: int):
        captured.append(list(images))
        payload = json.loads(user_text) if user_text.strip().startswith("{") else {}
        return {
            "suggested_dt": "DT-02",
            "confidence": 0.85,
            "vendor": "Acme",
            "line_items": [],
            "field_confidence": {},
            **payload,
        }

    ocr_non_sparse = OcrArtifact(success=True, sparse=False, text="full text", text_length=9)
    ocr_sparse = OcrArtifact(success=True, sparse=True, text="blur", text_length=4)

    with patch(
        "app.services.extraction.azure_foundry_vision_client._vision_json",
        new=AsyncMock(side_effect=_fake_vision),
    ):
        with patch(
            "app.services.extraction.azure_foundry_vision_client.resolve_pdf_page_images",
            side_effect=lambda path, cache=None: cache if cache else [b"cached-page"],
        ) as mock_resolve:
            await extract_fields_azure_foundry(
                ocr_non_sparse,
                pdf_path,
                org=OrgContext(),
                document_types=[],
                confirmed_dt="DT-01",
                vision_page_images=cache,
            )
            await extract_fields_azure_foundry(
                ocr_sparse,
                pdf_path,
                org=OrgContext(),
                document_types=[],
                confirmed_dt="DT-02",
                vision_page_images=cache,
            )

    mock_resolve.assert_called_once()
    assert captured[0] == []
    assert captured[1] == [b"cached-page"]


@pytest.mark.asyncio
async def test_foundry_none_cache_backward_compat_rasterizes_per_call(tmp_path: Path) -> None:
    from app.services.extraction.azure_foundry_vision_client import extract_fields_azure_foundry

    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    ocr = OcrArtifact(success=True, sparse=True, text="blur", text_length=4)

    with patch(
        "app.services.extraction.azure_foundry_vision_client._vision_json",
        new=AsyncMock(
            return_value={
                "suggested_dt": "DT-01",
                "confidence": 0.8,
                "vendor": "Acme",
                "line_items": [],
                "field_confidence": {},
            }
        ),
    ):
        with patch(
            "app.services.extraction.vision_pdf.pdf_page_images",
            return_value=[b"page1"],
        ) as mock_raster:
            await extract_fields_azure_foundry(
                ocr,
                pdf_path,
                org=OrgContext(),
                document_types=[],
                confirmed_dt="DT-01",
                vision_page_images=None,
            )
            await extract_fields_azure_foundry(
                ocr,
                pdf_path,
                org=OrgContext(),
                document_types=[],
                confirmed_dt="DT-01",
                vision_page_images=None,
            )

    assert mock_raster.call_count == 2
