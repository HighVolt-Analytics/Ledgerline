"""Extract plain text from each PDF page (for multi-document segmentation)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.classification.catalogue_page_signals import infer_page_kind_token
from app.services.extraction.document_heading_utils import (
    infer_page_document_kind,
    is_continuation_page,
)
from app.services.extraction.document_intelligence import read_pdf_page_texts_via_di
from app.utils.logger import get_logger

logger = get_logger(__name__)

_THIN_PAGE_CHAR_THRESHOLD = 80
_NO_KIND_DI_CHAR_THRESHOLD = 250


@dataclass(frozen=True)
class PdfPageText:
    page_index: int
    text: str


@dataclass(frozen=True)
class PdfPageTextExtraction:
    """Page text plus OCR completeness metadata for split diagnostics."""

    pages: list[PdfPageText]
    incomplete_ocr_indices: tuple[int, ...] = ()


def _page_needs_di_upgrade(text: str) -> bool:
    """
    Decide whether a page should be OCR'd via Azure DI.

    Besides near-empty pages, include short local extracts that lack any document
    heading (common on scanned packing lists / AWBs where pdfplumber returns noise).
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return True
    if is_continuation_page(cleaned):
        return False
    if infer_page_kind_token(cleaned) is not None:
        return False
    if infer_page_document_kind(cleaned) is not None:
        return False
    if len(cleaned) < _THIN_PAGE_CHAR_THRESHOLD:
        return True
    if len(cleaned) >= _NO_KIND_DI_CHAR_THRESHOLD:
        return False
    return True


def thin_page_indices(pages: list[PdfPageText]) -> list[int]:
    """Page indices that still need OCR or lack usable heading text."""
    return [page.page_index for page in pages if _page_needs_di_upgrade(page.text or "")]


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
) -> tuple[list[PdfPageText], tuple[int, ...]]:
    """OCR image-only pages when local extract left gaps in a mixed PDF."""
    thin_indices = set(thin_page_indices(pages))
    if not thin_indices:
        return pages, ()

    ocr_pages = read_pdf_page_texts_via_di(path)
    if not ocr_pages:
        logger.warning(
            "pdf_split_ocr_incomplete",
            path=str(path),
            thin_pages=sorted(thin_indices),
            reason="di_unavailable",
        )
        return pages, tuple(sorted(thin_indices))

    ocr_by_index = {index: text for index, text in ocr_pages}
    merged: list[PdfPageText] = []
    upgraded = 0
    still_thin: list[int] = []
    for page in pages:
        if page.page_index in thin_indices:
            di_text = (ocr_by_index.get(page.page_index) or "").strip()
            if di_text:
                merged.append(PdfPageText(page_index=page.page_index, text=di_text))
                upgraded += 1
                continue
            still_thin.append(page.page_index)
        merged.append(page)

    if upgraded:
        logger.info(
            "pdf_page_text_hybrid_di",
            path=str(path),
            upgraded=upgraded,
            thin_pages=len(thin_indices),
        )
    if still_thin:
        logger.warning(
            "pdf_split_ocr_incomplete",
            path=str(path),
            thin_pages=still_thin,
            reason="di_page_empty",
        )
    return merged, tuple(still_thin)


def extract_pdf_page_texts_via_full_di(path: Path) -> PdfPageTextExtraction | None:
    """OCR every page via Azure DI — fallback when hybrid split preparation fails."""
    ocr_pages = read_pdf_page_texts_via_di(path)
    if not ocr_pages:
        return None
    di_pages = [PdfPageText(page_index=index, text=text) for index, text in ocr_pages]
    incomplete = tuple(
        page.page_index for page in di_pages if _page_needs_di_upgrade(page.text or "")
    )
    logger.info("pdf_page_text_full_di_fallback", path=str(path), pages=len(di_pages))
    return PdfPageTextExtraction(pages=di_pages, incomplete_ocr_indices=incomplete)


def extract_pdf_page_texts(path: Path) -> PdfPageTextExtraction:
    """Return one entry per page — local extract, hybrid DI for image pages, full DI when blank."""
    pages = _extract_local_page_texts(path)
    if pages and any(page.text.strip() for page in pages):
        merged, incomplete = _merge_thin_pages_with_di(pages, path)
        return PdfPageTextExtraction(pages=merged, incomplete_ocr_indices=incomplete)

    ocr_pages = read_pdf_page_texts_via_di(path)
    if ocr_pages:
        logger.info("pdf_page_text_via_di", path=str(path), pages=len(ocr_pages))
        di_pages = [PdfPageText(page_index=index, text=text) for index, text in ocr_pages]
        incomplete = tuple(
            page.page_index
            for page in di_pages
            if _page_needs_di_upgrade(page.text or "")
        )
        if incomplete:
            logger.warning(
                "pdf_split_ocr_incomplete",
                path=str(path),
                thin_pages=list(incomplete),
                reason="di_page_empty",
            )
        return PdfPageTextExtraction(pages=di_pages, incomplete_ocr_indices=incomplete)

    incomplete = tuple(thin_page_indices(pages))
    if incomplete:
        logger.warning(
            "pdf_split_ocr_incomplete",
            path=str(path),
            thin_pages=list(incomplete),
            reason="di_unavailable",
        )
    return PdfPageTextExtraction(pages=pages, incomplete_ocr_indices=incomplete)
