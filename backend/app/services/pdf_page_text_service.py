"""Extract plain text from each PDF page (for multi-document segmentation)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.document_intelligence import read_pdf_page_texts_via_di
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PdfPageText:
    page_index: int
    text: str


def _extract_local_page_texts(path: Path) -> list[PdfPageText]:
    pages: list[PdfPageText] = []
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            for index, page in enumerate(pdf.pages):
                pages.append(PdfPageText(page_index=index, text=page.extract_text() or ""))
        if pages:
            return pages
    except Exception as exc:
        logger.warning("pdfplumber_page_extract_failed", path=str(path), error=str(exc))

    try:
        import fitz

        doc = fitz.open(path)
        for index in range(doc.page_count):
            pages.append(PdfPageText(page_index=index, text=doc.load_page(index).get_text() or ""))
        doc.close()
    except Exception as exc:
        logger.warning("pymupdf_page_extract_failed", path=str(path), error=str(exc))
        return []

    return pages


def extract_pdf_page_texts(path: Path) -> list[PdfPageText]:
    """Return one entry per page — local extract, then Azure Read OCR when scanned."""
    pages = _extract_local_page_texts(path)
    if pages and any(page.text.strip() for page in pages):
        return pages

    ocr_pages = read_pdf_page_texts_via_di(path)
    if ocr_pages:
        logger.info("pdf_page_text_via_di", path=str(path), pages=len(ocr_pages))
        return [PdfPageText(page_index=index, text=text) for index, text in ocr_pages]

    return pages
