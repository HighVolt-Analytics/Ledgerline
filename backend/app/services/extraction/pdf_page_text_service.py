"""Extract plain text from each PDF page (for multi-document segmentation)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.extraction.document_intelligence import read_pdf_page_texts_via_di
from app.utils.logger import get_logger

logger = get_logger(__name__)

_THIN_PAGE_CHAR_THRESHOLD = 80


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


def _merge_thin_pages_with_di(
    pages: list[PdfPageText],
    path: Path,
) -> list[PdfPageText]:
    """OCR image-only pages when local extract left gaps in a mixed PDF."""
    thin_indices = {
        page.page_index
        for page in pages
        if len((page.text or "").strip()) < _THIN_PAGE_CHAR_THRESHOLD
    }
    if not thin_indices:
        return pages

    ocr_pages = read_pdf_page_texts_via_di(path)
    if not ocr_pages:
        return pages

    ocr_by_index = {index: text for index, text in ocr_pages}
    merged: list[PdfPageText] = []
    upgraded = 0
    for page in pages:
        if page.page_index in thin_indices:
            di_text = (ocr_by_index.get(page.page_index) or "").strip()
            if di_text:
                merged.append(PdfPageText(page_index=page.page_index, text=di_text))
                upgraded += 1
                continue
        merged.append(page)

    if upgraded:
        logger.info(
            "pdf_page_text_hybrid_di",
            path=str(path),
            upgraded=upgraded,
            thin_pages=len(thin_indices),
        )
    return merged


def extract_pdf_page_texts(path: Path) -> list[PdfPageText]:
    """Return one entry per page — local extract, hybrid DI for image pages, full DI when blank."""
    pages = _extract_local_page_texts(path)
    if pages and any(page.text.strip() for page in pages):
        return _merge_thin_pages_with_di(pages, path)

    ocr_pages = read_pdf_page_texts_via_di(path)
    if ocr_pages:
        logger.info("pdf_page_text_via_di", path=str(path), pages=len(ocr_pages))
        return [PdfPageText(page_index=index, text=text) for index, text in ocr_pages]

    return pages
