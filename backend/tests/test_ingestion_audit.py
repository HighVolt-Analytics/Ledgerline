"""Image ingestion and digital-PDF audit tests."""

from __future__ import annotations

from pathlib import Path

from app.services.extraction.pdf_parser import _content_type_for_path
from app.services.extraction.pdf_page_text_service import (
    PdfPageText,
    thin_page_indices,
    _page_needs_di_upgrade,
)


def test_image_content_types_for_di() -> None:
    assert _content_type_for_path(Path("scan.jpg")) == "image/jpeg"
    assert _content_type_for_path(Path("scan.png")) == "image/png"
    assert _content_type_for_path(Path("doc.pdf")) == "application/pdf"


def test_digital_pdf_page_skips_di_upgrade() -> None:
    text = "TAX INVOICE\nVendor: ACME LTD\nInvoice No: INV-1001\nTotal: $1,234.56\n" * 3
    assert _page_needs_di_upgrade(text) is False


def test_thin_page_still_needs_di() -> None:
    assert _page_needs_di_upgrade("x") is True
    assert 0 in thin_page_indices([PdfPageText(page_index=0, text="x")])
