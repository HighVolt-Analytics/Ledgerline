"""Image/DOCX ingest fingerprints — avoid false T4 possible-duplicate badges."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.extraction.pdf_page_text_service import (
    PdfPageText,
    PdfPageTextExtraction,
    extract_non_pdf_page_texts_via_di,
    is_fingerprintable_non_pdf,
)
from app.services.dossier.document_duplicate_service import (
    refresh_duplicate_review_after_ocr,
    signals_are_sparse,
)
from app.services.ingest.ingest_fanout_service import (
    _fingerprints_from_pages,
    _prepare_non_pdf_fingerprint_pages,
)
from app.services.ingest.page_fingerprint_service import collect_page_fingerprints


_LONG_INVOICE = (
    "ACME SUPPLIES PTY LTD\n"
    "TAX INVOICE INV-9001\n"
    "Date: 15 July 2026\n"
    "Bill To: High Volt Analytics\n"
    "Line items and totals appear below with enough text for fingerprinting.\n"
    "Subtotal 100.00 GST 10.00 Total 110.00 AUD payable within 30 days.\n"
)


def test_is_fingerprintable_non_pdf_covers_images_and_docx() -> None:
    assert is_fingerprintable_non_pdf("scan.PNG")
    assert is_fingerprintable_non_pdf("photo.jpg")
    assert is_fingerprintable_non_pdf("photo.jpeg")
    assert is_fingerprintable_non_pdf("claim.docx")
    assert not is_fingerprintable_non_pdf("shot.webp")  # Azure DI unsupported
    assert not is_fingerprintable_non_pdf("doc.pdf")
    assert not is_fingerprintable_non_pdf("readme.txt")


def test_extract_non_pdf_page_texts_via_di(tmp_path: Path) -> None:
    path = tmp_path / "invoice.png"
    path.write_bytes(b"\x89PNG fake")
    di_pages = [(0, _LONG_INVOICE)]

    with patch(
        "app.services.extraction.pdf_page_text_service.read_pdf_page_texts_via_di",
        return_value=di_pages,
    ) as mock_di:
        result = extract_non_pdf_page_texts_via_di(path)

    mock_di.assert_called_once()
    assert mock_di.call_args.kwargs.get("content_type") == "image/png"
    assert result is not None
    assert len(result.pages) == 1
    assert "INV-9001" in result.pages[0].text


def test_extract_non_pdf_skips_unsupported_suffix(tmp_path: Path) -> None:
    path = tmp_path / "shot.webp"
    path.write_bytes(b"RIFF")
    with patch(
        "app.services.extraction.pdf_page_text_service.read_pdf_page_texts_via_di",
    ) as mock_di:
        assert extract_non_pdf_page_texts_via_di(path) is None
    mock_di.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_non_pdf_fingerprint_pages_uses_di() -> None:
    pages = [PdfPageText(page_index=0, text=_LONG_INVOICE)]
    with patch(
        "app.services.ingest.ingest_fanout_service.extract_non_pdf_page_texts_via_di",
        return_value=PdfPageTextExtraction(pages=pages),
    ):
        got = await _prepare_non_pdf_fingerprint_pages(
            filename="INV_1250.png",
            data=b"\x89PNG bytes",
        )
    assert got is not None
    assert got[0].text == _LONG_INVOICE


def test_image_pages_produce_non_sparse_signals() -> None:
    pages = [PdfPageText(page_index=0, text=_LONG_INVOICE)]
    content_fp, business_fp, identity = _fingerprints_from_pages(
        pages,
        custom_field_keys=[],
    )
    page_fps = [fp for _, fp in collect_page_fingerprints(pages)]
    assert content_fp
    assert page_fps
    assert not signals_are_sparse(
        content_fingerprint=content_fp,
        business_fingerprint=business_fp,
        identity_fields=identity,
        page_fingerprints=page_fps,
    )


@pytest.mark.asyncio
async def test_refresh_duplicate_review_clears_when_ocr_rich() -> None:
    invoice = MagicMock()
    invoice.id = 42
    invoice.tenant_id = 1
    invoice.duplicate_review_suggested = True
    invoice.content_fingerprint = None
    invoice.business_fingerprint = None

    session = AsyncMock()
    with (
        patch(
            "app.services.dossier.document_duplicate_service.find_invoice_by_content_fingerprint_for_ingest",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.services.dossier.document_duplicate_service.find_invoice_by_business_fingerprint_for_ingest",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.services.ingest.page_fingerprint_service.persist_invoice_page_fingerprints",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "app.services.dossier.document_duplicate_service.log_event",
            new_callable=AsyncMock,
        ) as mock_log,
    ):
        cleared = await refresh_duplicate_review_after_ocr(
            session,
            invoice,
            ocr_text=_LONG_INVOICE,
        )

    assert cleared is True
    assert invoice.duplicate_review_suggested is False
    assert invoice.content_fingerprint
    mock_log.assert_awaited()
    assert mock_log.await_args.args[1] == "duplicate_review_cleared"


@pytest.mark.asyncio
async def test_refresh_duplicate_review_keeps_flag_on_empty_ocr() -> None:
    invoice = MagicMock()
    invoice.duplicate_review_suggested = True
    session = AsyncMock()
    cleared = await refresh_duplicate_review_after_ocr(session, invoice, ocr_text="  ")
    assert cleared is False
    assert invoice.duplicate_review_suggested is True
