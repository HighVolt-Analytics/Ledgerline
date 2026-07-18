"""Deterministic PDF page grouping — mirrors LLM segment prompt decision order.

Window per page: previous (i-1) | current (i) | upcoming (i+1) | upcoming_2 (i+2)

Decision order:
  (1) LOOK BACK — type/identity vs open run → new doc starts here? (skip on page 0)
  (2) LOOK AHEAD CONTINUE — upcoming same type+identity / continuation → keep in run
  (3) LOOK AHEAD TYPE CHANGE — upcoming different type → close run before that page
Blank / empty pages never start a segment; they attach to the nearest real document.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.classification.catalogue_page_signals import (
    CataloguePageMatcher,
    build_catalogue_page_matchers,
    heading_kind_from_token,
    infer_page_kind_token,
)
from app.services.extraction.document_heading_utils import (
    HeadingKind,
    extract_document_heading_signals,
    is_continuation_page,
)
from app.services.extraction.document_identity_service import page_identity_signature
from app.services.extraction.permit_ocr_extractors import extract_permit_fields_from_text
from app.services.extraction.pdf_page_text_service import PdfPageText
from app.schemas.document_type import DocumentTypeDefinition
from app.utils.logger import get_logger

logger = get_logger(__name__)

_BLANK_PAGE_MARKERS = (
    "this page intentionally left blank",
    "intentionally left blank",
    "blank page",
    "empty page",
)


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


def page_is_blank_for_segment(page: PdfPageText) -> bool:
    """True when the page should not stand alone as a document segment."""
    text = (page.text or "").strip()
    if not text:
        return True
    lowered = " ".join(text.lower().split())
    if len(lowered) <= 40 and any(marker in lowered for marker in _BLANK_PAGE_MARKERS):
        return True
    return False


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
    if page_is_blank_for_segment(page):
        return False
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


def _next_signal_page(
    pages: list[PdfPageText],
    start: int,
    *,
    matchers: list[CataloguePageMatcher] | None,
) -> int | None:
    """Next non-blank page index with a document signal (kind or continuation)."""
    for index in range(start, len(pages)):
        page = pages[index]
        if page_is_blank_for_segment(page):
            continue
        if _page_kind_token(page, matchers=matchers) or is_continuation_page(page.text or ""):
            return index
        if (page.text or "").strip():
            return index
    return None


def _kinds_compatible(open_kinds: frozenset[str], page_kinds: frozenset[str]) -> bool:
    if not open_kinds or not page_kinds:
        return True
    return bool(open_kinds & page_kinds)


def _single_segment(
    pages: list[PdfPageText],
    *,
    matchers: list[CataloguePageMatcher] | None,
    custom_field_keys: list[str] | None,
    document_types: list[DocumentTypeDefinition] | None = None,
) -> PdfDocumentSegment:
    kind_token = None
    for page in pages:
        kind_token = _page_kind_token(page, matchers=matchers)
        if kind_token:
            break
    kind = _resolve_heading_kind(kind_token, document_types=document_types)
    last = max(len(pages) - 1, 0)
    seed = next((p for p in pages if not page_is_blank_for_segment(p)), pages[0] if pages else None)
    identity = (
        page_identity_signature(
            seed.text,
            page_kind_token=kind_token,
            custom_field_keys=custom_field_keys,
        )
        if seed is not None
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
    """Bidirectional window walk matching the LLM segment prompt."""
    starts: list[tuple[int, float]] = [(0, 1.0)]

    # Seed open-run state from first real (non-blank) page when possible.
    seed_idx = _next_signal_page(pages, 0, matchers=matchers) or 0
    open_kind = _page_kind_token(pages[seed_idx], matchers=matchers)
    open_key = page_identity_signature(
        pages[seed_idx].text,
        page_kind_token=open_kind,
        custom_field_keys=custom_field_keys,
    )
    open_kinds = _page_all_kind_tokens(pages[seed_idx], matchers=matchers)
    open_permit_no = (
        _segment_permit_no(pages, seed_idx)
        if heading_kind_from_token(open_kind) == "customs_permit"
        else None
    )

    index = 1
    while index < len(pages):
        page = pages[index]

        # --- Blank / noise: never start; attach to open run; peek ahead for type change ---
        if page_is_blank_for_segment(page) and not _page_starts_new_document(
            page, matchers=matchers
        ):
            ahead_idx = _next_signal_page(pages, index + 1, matchers=matchers)
            if ahead_idx is not None:
                ahead = pages[ahead_idx]
                ahead_kind = _page_kind_token(ahead, matchers=matchers)
                ahead_kinds = _page_all_kind_tokens(ahead, matchers=matchers)
                ahead_key = page_identity_signature(
                    ahead.text,
                    page_kind_token=ahead_kind,
                    custom_field_keys=custom_field_keys,
                )
                type_change = bool(
                    ahead_kind
                    and open_kind
                    and ahead_kind != open_kind
                    and not _kinds_compatible(open_kinds, ahead_kinds)
                )
                identity_change = bool(
                    ahead_key and open_key and ahead_key != open_key and ahead_kind
                )
                if type_change or (aggressive and identity_change):
                    # (3) LOOK AHEAD TYPE CHANGE — close open run before ahead; blank stays prior.
                    starts.append((ahead_idx, 0.88 if type_change else 0.78))
                    open_kind = ahead_kind
                    open_key = ahead_key
                    open_kinds = ahead_kinds
                    open_permit_no = (
                        _segment_permit_no(pages, ahead_idx)
                        if heading_kind_from_token(ahead_kind) == "customs_permit"
                        else None
                    )
                    index = ahead_idx + 1
                    continue
            index += 1
            continue

        if _page_continues_permit_segment(page, segment_permit_no=open_permit_no):
            open_kinds = open_kinds | _page_all_kind_tokens(page, matchers=matchers)
            index += 1
            continue

        page_kinds = _page_all_kind_tokens(page, matchers=matchers)
        kind = _page_kind_token(page, matchers=matchers)
        key = page_identity_signature(
            page.text,
            page_kind_token=kind,
            custom_field_keys=custom_field_keys,
        )
        starts_new = _page_starts_new_document(page, matchers=matchers)
        continuation = is_continuation_page(page.text or "")

        # (2) LOOK AHEAD CONTINUE — upcoming same type+identity keeps this page in open run
        upcoming_idx = _next_signal_page(pages, index + 1, matchers=matchers)
        upcoming_kind = None
        upcoming_key = None
        if upcoming_idx is not None:
            upcoming = pages[upcoming_idx]
            upcoming_kind = _page_kind_token(upcoming, matchers=matchers)
            upcoming_key = page_identity_signature(
                upcoming.text,
                page_kind_token=upcoming_kind,
                custom_field_keys=custom_field_keys,
            )

        # (1) LOOK BACK — does a NEW document start at i?
        split = False
        confidence = 0.0
        if continuation:
            split = False
        elif kind and open_kind and kind != open_kind and not _kinds_compatible(
            open_kinds, page_kinds
        ):
            split = True
            confidence = 0.92
        elif starts_new and key and open_key and key != open_key:
            split = True
            confidence = 0.85
        elif starts_new and kind and not open_kind:
            split = True
            confidence = 0.8
        elif (
            aggressive
            and key
            and open_key
            and key != open_key
            and (starts_new or bool(kind))
        ):
            split = True
            confidence = 0.78

        # Weak current page: if look-ahead shows a clear type change vs open run,
        # keep current with open run (do not split here); the ahead page will start next.
        if (
            not split
            and not starts_new
            and upcoming_kind
            and open_kind
            and upcoming_kind != open_kind
        ):
            # stay in open run; upcoming handled when index reaches it
            pass

        if split:
            starts.append((index, confidence))
            open_kind = kind
            open_key = key
            open_kinds = page_kinds
            open_permit_no = (
                _segment_permit_no(pages, index)
                if heading_kind_from_token(kind) == "customs_permit"
                else None
            )
        else:
            # Extend open run; refresh kind/key when this page strengthens the signal.
            if kind:
                open_kind = kind
            if key:
                open_key = key
            open_kinds = open_kinds | page_kinds
            # (2) If upcoming continues same type+identity, we simply advance — extent grows.
            if (
                upcoming_kind
                and open_kind
                and upcoming_kind == open_kind
                and upcoming_key
                and open_key
                and upcoming_key == open_key
            ):
                pass

        index += 1

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
        # Prefer heading from first non-blank page in the range.
        kind_token = None
        identity_text = pages[start].text
        for page_idx in range(start, end + 1):
            token = _page_kind_token(pages[page_idx], matchers=matchers)
            if token:
                kind_token = token
                identity_text = pages[page_idx].text
                break
        kind = _resolve_heading_kind(kind_token, document_types=document_types)
        identity = page_identity_signature(
            identity_text,
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


def merge_blank_only_rule_segments(
    result: PdfSegmentResult,
    pages: list[PdfPageText],
) -> PdfSegmentResult:
    """Omit blank pages from rule segments (do not attach blanks to neighbors)."""
    from app.services.extraction.pdf_segment_llm_service import drop_blank_pages_from_segments

    return drop_blank_pages_from_segments(result, pages)


def segment_pdf_pages(
    pages: list[PdfPageText],
    *,
    max_segments: int = 20,
    document_types: list[DocumentTypeDefinition] | None = None,
    custom_field_keys: list[str] | None = None,
    catalogue_matchers: list[CataloguePageMatcher] | None = None,
) -> PdfSegmentResult:
    """
    Group consecutive pages into documents using bidirectional window rules
    (same decision order as pdf.segment.system prompt).
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
        return merge_blank_only_rule_segments(
            PdfSegmentResult(
                segments=segments,
                cap_exceeded=True,
                detected_boundary_count=len(starts),
            ),
            pages,
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
                return merge_blank_only_rule_segments(
                    PdfSegmentResult(
                        segments=segments,
                        cap_exceeded=True,
                        detected_boundary_count=len(aggressive_starts),
                    ),
                    pages,
                )
            starts = aggressive_starts

    return merge_blank_only_rule_segments(
        PdfSegmentResult(
            segments=segments,
            detected_boundary_count=len(starts),
            cap_exceeded=cap_exceeded,
        ),
        pages,
    )


def purchase_document_type_from_heading(kind: HeadingKind | None) -> str | None:
    if kind == "purchase_order":
        return "po"
    if kind == "grn":
        return "grn"
    if kind in {"invoice", "tax_invoice", "commercial_invoice", "credit_note", "proforma"}:
        return "invoice"
    return None
