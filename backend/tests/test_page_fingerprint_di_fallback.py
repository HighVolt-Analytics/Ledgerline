"""Phase 2: DI fallback recovers page fingerprints or leaves T4 only."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.extraction.pdf_page_text_service import (
    PdfPageText,
    PdfPageTextExtraction,
)
from app.services.ingest.page_fingerprint_service import (
    collect_page_fingerprints,
    enrich_pages_for_fingerprints,
    persist_invoice_page_fingerprints,
)


_LONG_PAGE = (
    "ACME SUPPLIES PTY LTD\n"
    "TAX INVOICE INV-9001\n"
    "Date: 15 July 2026\n"
    "Bill To: High Volt Analytics\n"
    "Line items and totals appear below with enough text for fingerprinting.\n"
    "Subtotal 100.00 GST 10.00 Total 110.00 AUD payable within 30 days.\n"
)


def test_enrich_pages_recovers_fingerprints_via_full_di(tmp_path: Path) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 empty local extract")

    empty_local = [PdfPageText(page_index=0, text="")]
    di_pages = [PdfPageText(page_index=0, text=_LONG_PAGE)]

    with patch(
        "app.services.extraction.pdf_page_text_service.extract_pdf_page_texts_via_full_di",
        return_value=PdfPageTextExtraction(pages=di_pages),
    ) as mock_di:
        enriched = enrich_pages_for_fingerprints(pdf_path, empty_local)

    mock_di.assert_called_once_with(pdf_path)
    assert enriched is not None
    pairs = collect_page_fingerprints(enriched)
    assert len(pairs) == 1
    assert pairs[0][0] == 0
    assert pairs[0][1]


def test_enrich_pages_skips_di_when_local_fps_present(tmp_path: Path) -> None:
    pdf_path = tmp_path / "text.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    local = [PdfPageText(page_index=0, text=_LONG_PAGE)]

    with patch(
        "app.services.extraction.pdf_page_text_service.extract_pdf_page_texts_via_full_di",
    ) as mock_di:
        enriched = enrich_pages_for_fingerprints(pdf_path, local)

    mock_di.assert_not_called()
    assert enriched is local
    assert collect_page_fingerprints(enriched)


def test_enrich_pages_di_fail_leaves_empty_for_t4(tmp_path: Path) -> None:
    """No fake fingerprints — empty after DI stays empty (T4 path)."""
    pdf_path = tmp_path / "blank.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    empty_local = [PdfPageText(page_index=0, text="")]

    with patch(
        "app.services.extraction.pdf_page_text_service.extract_pdf_page_texts_via_full_di",
        return_value=None,
    ):
        enriched = enrich_pages_for_fingerprints(pdf_path, empty_local)

    assert enriched is empty_local
    assert collect_page_fingerprints(enriched) == []


def test_enrich_pages_di_thin_text_no_fake_fingerprints(tmp_path: Path) -> None:
    pdf_path = tmp_path / "thin.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    empty_local = [PdfPageText(page_index=0, text="")]
    thin_di = [PdfPageText(page_index=0, text="hi")]

    with patch(
        "app.services.extraction.pdf_page_text_service.extract_pdf_page_texts_via_full_di",
        return_value=PdfPageTextExtraction(pages=thin_di),
    ):
        enriched = enrich_pages_for_fingerprints(pdf_path, empty_local)

    assert enriched is thin_di
    assert collect_page_fingerprints(enriched) == []


@pytest.mark.asyncio
async def test_persist_page_fingerprints_replaces_existing_rows() -> None:
    """Post-vision split re-persists on the same invoice_id — must delete first."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    pages = [PdfPageText(page_index=0, text=_LONG_PAGE)]

    count = await persist_invoice_page_fingerprints(
        session,
        tenant_id=uuid.uuid4(),
        invoice_id=389,
        pages=pages,
    )

    assert count == 1
    session.execute.assert_awaited()
    session.add.assert_called_once()
    session.flush.assert_awaited()
