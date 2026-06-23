"""Deterministic PDF page grouping into logical documents (heading + key fields)."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.document_heading_utils import HeadingKind, infer_page_document_kind
from app.services.pdf_page_text_service import PdfPageText
from app.services.pdf_parser import parse_text_fields
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PdfDocumentSegment:
    start_page: int
    end_page: int
    heading_kind: HeadingKind | None
    boundary_confidence: float


def _page_heading_kind(page: PdfPageText) -> HeadingKind | None:
    return infer_page_document_kind(page.text)


def _page_starts_new_document(page: PdfPageText) -> bool:
    return infer_page_document_kind(page.text) is not None


def _segment_identity_key(page: PdfPageText, kind: HeadingKind | None) -> str | None:
    if kind is None:
        return None
    fields = parse_text_fields(page.text)
    if kind == "purchase_order":
        token = (fields.get("po_reference") or "").strip()
        return token or None
    if kind in {"invoice", "tax_invoice", "commercial_invoice", "credit_note", "proforma"}:
        token = (fields.get("invoice_no") or "").strip()
        return token or None
    return kind


def _single_segment(pages: list[PdfPageText]) -> PdfDocumentSegment:
    kind = _page_heading_kind(pages[0]) if pages else None
    last = max(len(pages) - 1, 0)
    return PdfDocumentSegment(start_page=0, end_page=last, heading_kind=kind, boundary_confidence=1.0)


def segment_pdf_pages(
    pages: list[PdfPageText],
    *,
    max_segments: int = 20,
) -> list[PdfDocumentSegment]:
    """
    Group consecutive pages into documents.

    A new segment starts when a page header signals a different document kind,
    or the same invoice-like kind with a different invoice/PO identifier.
    """
    if not pages:
        return [PdfDocumentSegment(0, 0, None, 1.0)]
    if len(pages) == 1:
        return [_single_segment(pages)]

    starts: list[tuple[int, float]] = [(0, 1.0)]
    prev_kind = _page_heading_kind(pages[0])
    prev_key = _segment_identity_key(pages[0], prev_kind)

    for index in range(1, len(pages)):
        page = pages[index]
        if not _page_starts_new_document(page):
            continue

        kind = _page_heading_kind(page)
        key = _segment_identity_key(page, kind)
        confidence = 0.0
        split = False

        if kind is not None and prev_kind is not None and kind != prev_kind:
            split = True
            confidence = 0.9
        elif key and prev_key and key != prev_key:
            split = True
            confidence = 0.85
        elif kind is not None and prev_kind is not None and kind == prev_kind:
            split = True
            confidence = 0.75
        elif kind is not None and prev_kind is None:
            split = True
            confidence = 0.8

        if split:
            starts.append((index, confidence))
            prev_kind = kind
            prev_key = key
        elif kind is not None:
            prev_kind = kind
            if key:
                prev_key = key

    if len(starts) == 1:
        return [_single_segment(pages)]

    if len(starts) > max_segments:
        logger.warning("pdf_segment_cap_exceeded", detected=len(starts), cap=max_segments)
        return [_single_segment(pages)]

    segments: list[PdfDocumentSegment] = []
    for idx, (start, confidence) in enumerate(starts):
        end = starts[idx + 1][0] - 1 if idx + 1 < len(starts) else len(pages) - 1
        kind = _page_heading_kind(pages[start])
        segments.append(
            PdfDocumentSegment(
                start_page=start,
                end_page=end,
                heading_kind=kind,
                boundary_confidence=confidence if idx > 0 else 1.0,
            )
        )
    return segments


def purchase_document_type_from_heading(kind: HeadingKind | None) -> str | None:
    if kind == "purchase_order":
        return "po"
    if kind == "grn":
        return "grn"
    if kind in {"invoice", "tax_invoice", "commercial_invoice", "credit_note", "proforma"}:
        return "invoice"
    return None
