"""Deterministic PDF page grouping into logical documents (heading + key fields)."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.classification.catalogue_page_signals import (
    CataloguePageMatcher,
    build_catalogue_page_matchers,
    heading_kind_from_token,
    infer_page_kind_token,
)
from app.services.extraction.document_heading_utils import HeadingKind, extract_document_heading_signals, is_continuation_page
from app.services.extraction.document_identity_service import page_identity_signature
from app.services.extraction.permit_ocr_extractors import extract_permit_fields_from_text
from app.services.extraction.pdf_page_text_service import PdfPageText
from app.schemas.document_type import DocumentTypeDefinition
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PdfDocumentSegment:
    start_page: int
    end_page: int
    heading_kind: HeadingKind | None
    boundary_confidence: float
    page_kind_token: str | None = None
    identity_signature: str | None = None


@dataclass(frozen=True)
class PdfSegmentResult:
    segments: list[PdfDocumentSegment]
    cap_exceeded: bool = False
    detected_boundary_count: int = 0
    segmentation_method: str = "rules"
    llm_reasoning: str | None = None


def _page_kind_token(
    page: PdfPageText,
    *,
    matchers: list[CataloguePageMatcher] | None,
) -> str | None:
    return infer_page_kind_token(page.text, matchers=matchers)


def _page_all_kind_tokens(page: PdfPageText, *, matchers: list[CataloguePageMatcher] | None) -> frozenset[str]:
    tokens: set[str] = set()
    kind_token = _page_kind_token(page, matchers=matchers)
    if kind_token:
        tokens.add(kind_token)
    signals = extract_document_heading_signals(page.text)
    for kind in signals.kinds:
        tokens.add(f"kind:{kind}")
    return frozenset(tokens)


def _page_starts_new_document(page: PdfPageText, *, matchers: list[CataloguePageMatcher] | None) -> bool:
    if is_continuation_page(page.text):
        return False
    return _page_kind_token(page, matchers=matchers) is not None


def _segment_permit_no(pages: list[PdfPageText], start: int) -> str | None:
    for index in range(start, len(pages)):
        permit_no = extract_permit_fields_from_text(pages[index].text).get("permit_no")
        if permit_no:
            return permit_no
    return None


def _page_continues_permit_segment(
    page: PdfPageText,
    *,
    segment_permit_no: str | None,
) -> bool:
    if not segment_permit_no:
        return False
    if is_continuation_page(page.text):
        return True
    page_permit = extract_permit_fields_from_text(page.text).get("permit_no")
    return bool(page_permit and page_permit == segment_permit_no)


def _resolve_heading_kind(
    kind_token: str | None,
    *,
    document_types: list[DocumentTypeDefinition] | None,
) -> HeadingKind | None:
    return heading_kind_from_token(kind_token, document_types=document_types)  # type: ignore[return-value]


def _single_segment(
    pages: list[PdfPageText],
    *,
    matchers: list[CataloguePageMatcher] | None,
    custom_field_keys: list[str] | None,
    document_types: list[DocumentTypeDefinition] | None = None,
) -> PdfDocumentSegment:
    kind_token = _page_kind_token(pages[0], matchers=matchers) if pages else None
    kind = _resolve_heading_kind(kind_token, document_types=document_types)
    last = max(len(pages) - 1, 0)
    identity = (
        page_identity_signature(
            pages[0].text,
            page_kind_token=kind_token,
            custom_field_keys=custom_field_keys,
        )
        if pages
        else None
    )
    return PdfDocumentSegment(
        start_page=0,
        end_page=last,
        heading_kind=kind,
        boundary_confidence=1.0,
        page_kind_token=kind_token,
        identity_signature=identity,
    )


def _segment_boundaries(
    pages: list[PdfPageText],
    *,
    matchers: list[CataloguePageMatcher] | None,
    custom_field_keys: list[str] | None,
    aggressive: bool,
) -> list[tuple[int, float]]:
    starts: list[tuple[int, float]] = [(0, 1.0)]
    prev_kind = _page_kind_token(pages[0], matchers=matchers)
    prev_key = page_identity_signature(
        pages[0].text,
        page_kind_token=prev_kind,
        custom_field_keys=custom_field_keys,
    )
    segment_kinds = _page_all_kind_tokens(pages[0], matchers=matchers)
    segment_permit_no = (
        _segment_permit_no(pages, 0)
        if heading_kind_from_token(prev_kind) == "customs_permit"
        else None
    )

    for index in range(1, len(pages)):
        page = pages[index]
        if _page_continues_permit_segment(page, segment_permit_no=segment_permit_no):
            segment_kinds = segment_kinds | _page_all_kind_tokens(page, matchers=matchers)
            continue

        page_kinds = _page_all_kind_tokens(page, matchers=matchers)
        new_kinds = page_kinds - segment_kinds
        has_new_kind = bool(page_kinds) and bool(new_kinds)
        starts_new = _page_starts_new_document(page, matchers=matchers)

        kind = _page_kind_token(page, matchers=matchers)
        key = page_identity_signature(
            page.text,
            page_kind_token=kind,
            custom_field_keys=custom_field_keys,
        )

        if (
            not aggressive
            and not starts_new
            and not has_new_kind
            and not (page.text or "").strip()
            and prev_kind
        ):
            for j in range(index + 1, len(pages)):
                ahead = pages[j]
                if is_continuation_page(ahead.text or ""):
                    continue
                ahead_kind = _page_kind_token(ahead, matchers=matchers)
                if not ahead_kind:
                    continue
                if ahead_kind != prev_kind:
                    ahead_key = page_identity_signature(
                        ahead.text,
                        page_kind_token=ahead_kind,
                        custom_field_keys=custom_field_keys,
                    )
                    starts.append((j, 0.75))
                    prev_kind = ahead_kind
                    prev_key = ahead_key
                    segment_kinds = _page_all_kind_tokens(ahead, matchers=matchers)
                    segment_permit_no = (
                        _segment_permit_no(pages, j)
                        if heading_kind_from_token(ahead_kind) == "customs_permit"
                        else None
                    )
                break
            continue

        if aggressive and not starts_new and not has_new_kind:
            if key and prev_key and key != prev_key:
                starts.append((index, 0.78))
                prev_kind = kind
                prev_key = key
                segment_kinds = page_kinds
                segment_permit_no = (
                    _segment_permit_no(pages, index)
                    if heading_kind_from_token(kind) == "customs_permit"
                    else None
                )
            elif not (page.text or "").strip():
                continue
            else:
                continue
            continue

        if not starts_new and not has_new_kind:
            continue

        confidence = 0.0
        split = False

        if kind and prev_kind and kind != prev_kind:
            split = True
            confidence = 0.9
        elif key and prev_key and key != prev_key:
            split = True
            confidence = 0.85
        elif has_new_kind and kind:
            split = True
            confidence = 0.82
        elif kind and not prev_kind:
            split = True
            confidence = 0.8

        if split:
            starts.append((index, confidence))
            prev_kind = kind
            prev_key = key
            segment_kinds = page_kinds
            segment_permit_no = (
                _segment_permit_no(pages, index)
                if heading_kind_from_token(kind) == "customs_permit"
                else None
            )
        elif kind:
            prev_kind = kind
            if key:
                prev_key = key
            segment_kinds = segment_kinds | page_kinds

    return starts


def _segments_from_starts(
    pages: list[PdfPageText],
    starts: list[tuple[int, float]],
    *,
    matchers: list[CataloguePageMatcher] | None,
    custom_field_keys: list[str] | None,
    document_types: list[DocumentTypeDefinition] | None,
    max_segments: int,
) -> tuple[list[PdfDocumentSegment], bool]:
    if len(starts) == 1:
        return (
            [_single_segment(
                pages,
                matchers=matchers,
                custom_field_keys=custom_field_keys,
                document_types=document_types,
            )],
            False,
        )

    if len(starts) > max_segments:
        logger.warning("pdf_segment_cap_exceeded", detected=len(starts), cap=max_segments)
        return (
            [_single_segment(
                pages,
                matchers=matchers,
                custom_field_keys=custom_field_keys,
                document_types=document_types,
            )],
            True,
        )

    segments: list[PdfDocumentSegment] = []
    for idx, (start, confidence) in enumerate(starts):
        end = starts[idx + 1][0] - 1 if idx + 1 < len(starts) else len(pages) - 1
        kind_token = _page_kind_token(pages[start], matchers=matchers)
        kind = _resolve_heading_kind(kind_token, document_types=document_types)
        identity = page_identity_signature(
            pages[start].text,
            page_kind_token=kind_token,
            custom_field_keys=custom_field_keys,
        )
        segments.append(
            PdfDocumentSegment(
                start_page=start,
                end_page=end,
                heading_kind=kind,
                boundary_confidence=confidence if idx > 0 else 1.0,
                page_kind_token=kind_token,
                identity_signature=identity,
            )
        )
    return segments, False


def segment_pdf_pages(
    pages: list[PdfPageText],
    *,
    max_segments: int = 20,
    document_types: list[DocumentTypeDefinition] | None = None,
    custom_field_keys: list[str] | None = None,
    catalogue_matchers: list[CataloguePageMatcher] | None = None,
) -> PdfSegmentResult:
    """
    Group consecutive pages into documents using catalogue + identity signatures.

    Runs a secondary aggressive pass when the primary scan yields a single segment
    for a multi-page PDF.
    """
    if not pages:
        return PdfSegmentResult(segments=[PdfDocumentSegment(0, 0, None, 1.0)])
    if len(pages) == 1:
        matchers = catalogue_matchers or (
            build_catalogue_page_matchers(document_types) if document_types else []
        )
        return PdfSegmentResult(
            segments=[_single_segment(
                pages,
                matchers=matchers,
                custom_field_keys=custom_field_keys,
                document_types=document_types,
            )]
        )

    matchers = catalogue_matchers or (
        build_catalogue_page_matchers(document_types) if document_types else []
    )

    starts = _segment_boundaries(
        pages,
        matchers=matchers,
        custom_field_keys=custom_field_keys,
        aggressive=False,
    )
    segments, cap_exceeded = _segments_from_starts(
        pages,
        starts,
        matchers=matchers,
        custom_field_keys=custom_field_keys,
        document_types=document_types,
        max_segments=max_segments,
    )

    if cap_exceeded:
        return PdfSegmentResult(
            segments=segments,
            cap_exceeded=True,
            detected_boundary_count=len(starts),
        )

    if len(segments) <= 1 and len(pages) > 1:
        aggressive_starts = _segment_boundaries(
            pages,
            matchers=matchers,
            custom_field_keys=custom_field_keys,
            aggressive=True,
        )
        if len(aggressive_starts) > 1:
            segments, cap_exceeded = _segments_from_starts(
                pages,
                aggressive_starts,
                matchers=matchers,
                custom_field_keys=custom_field_keys,
                document_types=document_types,
                max_segments=max_segments,
            )
            if cap_exceeded:
                return PdfSegmentResult(
                    segments=segments,
                    cap_exceeded=True,
                    detected_boundary_count=len(aggressive_starts),
                )
            starts = aggressive_starts

    return PdfSegmentResult(
        segments=segments,
        detected_boundary_count=len(starts),
    )


def purchase_document_type_from_heading(kind: HeadingKind | None) -> str | None:
    if kind == "purchase_order":
        return "po"
    if kind == "grn":
        return "grn"
    if kind in {"invoice", "tax_invoice", "commercial_invoice", "credit_note", "proforma"}:
        return "invoice"
    return None
