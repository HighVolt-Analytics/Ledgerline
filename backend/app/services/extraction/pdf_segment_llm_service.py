"""LLM-based PDF page boundary detection (batched, prompt-only)."""

from __future__ import annotations

import json
import re
from typing import Any, Sequence

from app.config import get_settings
from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.catalogue_page_signals import (
    CataloguePageMatcher,
    heading_kind_from_token,
)
from app.services.extraction.azure_openai_client import chat_json_async
from app.services.extraction.document_heading_utils import (
    HeadingKind,
    extract_document_heading_signals,
    infer_page_document_kind_with_source,
    is_continuation_page,
    parse_page_of_marker,
    warehouse_receipt_kind_from_text,
)
from app.services.extraction.document_identity_service import page_identity_signature
from app.services.extraction.pdf_page_text_service import PdfPageText
from app.services.extraction.pdf_segment_service import (
    PdfDocumentSegment,
    PdfSegmentResult,
    page_is_blank_for_segment,
    segment_pdf_pages,
)
from app.services.prompt_registry import resolve_system_prompt_text
from app.utils.logger import get_logger

logger = get_logger(__name__)

_PAGE_EXCERPT_MAX = 400

# Trailing boilerplate that must not become its own invoice.
_NON_DOCUMENT_MARKERS = (
    "disclaimer",
    "confidential",
    "terms and conditions",
    "terms & conditions",
    "this page intentionally left blank",
    "intentionally left blank",
    "for information only",
    "computer generated",
    "no signature required",
    "please do not reply",
    "this is an automated",
    "end of document",
    "continued on next page",  # alone on a page without content
    "not a tax invoice",
    "not an invoice",
    "is not a tax invoice",
)
_AMOUNT_RE = re.compile(
    r"""
    (?:
        \b(?:total|amount|subtotal|gst|balance|utilised|utilized)\b
        |\btax\s*(?:amount|total|inclusive|payable)\b
        |(?:AUD|USD|SGD|EUR|GBP|INR)\s*[$]?[\d,]+\.?\d*
        |[$€£₹]\s*[\d,]+\.?\d*
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_REF_IN_IDENTITY = ("invoice_no=", "po_reference=", "so_reference=", "bol_no=", "tracking_no=")
# Body-keyword kinds that often false-positive on T&Cs / footer pages.
_WEAK_STANDALONE_KINDS = frozenset(
    {"statement", "remittance", "quote", "contract", "timesheet"}
)


_HEADING_KINDS: tuple[str, ...] = (
    "tax_invoice",
    "commercial_invoice",
    "invoice",
    "purchase_order",
    "sales_order",
    "grn",
    "credit_note",
    "quote",
    "remittance",
    "proforma",
    "timesheet",
    "statement",
    "contract",
    "packing_list",
    "certificate_of_origin",
    "transport_doc",
    "customs_permit",
)


def _page_excerpt_max(page_count: int) -> int:
    """Keep excerpts short so large packs stay within TPM budgets."""
    if page_count > 24:
        return 180
    if page_count > 12:
        return 260
    return _PAGE_EXCERPT_MAX


def _page_kind_token_from_llm(
    heading_kind: str | None,
    suggested_dt: str | None,
) -> str | None:
    if heading_kind:
        return f"kind:{heading_kind}"
    dt = (suggested_dt or "").strip().upper()
    if dt:
        return f"dt:{dt}"
    return None


def _normalize_heading_kind(raw: str | None) -> HeadingKind | None:
    token = (raw or "").strip().lower()
    if not token:
        return None
    if token in _HEADING_KINDS:
        return token  # type: ignore[return-value]
    return None


_TITLE_REGION_MAX = 220


def _title_region(text: str, *, max_chars: int = _TITLE_REGION_MAX) -> str:
    """Top-of-page text used for before/after type comparison."""
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    # Prefer first lines (titles live at the top); keep enough for identity numbers.
    lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
    head = "\n".join(lines[:8]) if lines else cleaned
    return head[:max_chars]


def _page_title_hint(text: str) -> str:
    from app.services.extraction.document_heading_utils import infer_page_document_kind

    kind = infer_page_document_kind(text or "")
    return kind or ""


def _slim_catalogue(
    document_types: Sequence[DocumentTypeDefinition] | None,
) -> list[dict[str, str]]:
    """Codes + titles only — full recognition rules burn tokens and are unused for split."""
    rows: list[dict[str, str]] = []
    for defn in document_types or []:
        if not defn.enabled:
            continue
        code = (defn.code or "").strip().upper()
        if not code:
            continue
        rows.append({"code": code, "title": (defn.title or "").strip()})
    return rows


def build_segment_llm_user_payload(
    pages: list[PdfPageText],
    *,
    document_types: Sequence[DocumentTypeDefinition] | None,
) -> str:
    """Build lean LLM user JSON with i-1 | i | i+1 | i+2 window index refs.

    Avoids duplicating full page text inside every neighbor window (major TPM saver
    on 20–30 page packs).
    """
    excerpt_max = _page_excerpt_max(len(pages))
    title_regions = [_title_region(page.text or "") for page in pages]
    blank_flags = [page_is_blank_for_segment(page) for page in pages]
    title_hints = [_page_title_hint(page.text or "") for page in pages]

    def _neighbor(idx: int | None) -> dict[str, Any] | None:
        if idx is None or idx < 0 or idx >= len(pages):
            return None
        return {
            "page_index": idx,
            "title_region": title_regions[idx],
            "is_blank": blank_flags[idx],
            "title_hint": title_hints[idx],
        }

    page_rows: list[dict[str, Any]] = []
    for index, page in enumerate(pages):
        prev_idx = index - 1 if index > 0 else None
        next_idx = index + 1 if index + 1 < len(pages) else None
        next2_idx = index + 2 if index + 2 < len(pages) else None
        # Compact page body: title + short excerpt only (no full-page dump).
        page_rows.append(
            {
                "page_index": index,
                "is_blank": blank_flags[index],
                "title_hint": title_hints[index],
                "title_region": title_regions[index],
                "text_excerpt": (page.text or "")[:excerpt_max],
                "window": {
                    "previous": _neighbor(prev_idx),
                    "current": {
                        "page_index": index,
                        "is_blank": blank_flags[index],
                        "title_hint": title_hints[index],
                    },
                    "upcoming": _neighbor(next_idx),
                    "upcoming_2": _neighbor(next2_idx),
                },
            }
        )
    payload = {
        "page_count": len(pages),
        "decision_order": [
            "1_look_back: vs previous → does a NEW document start at i? (skip on page 0)",
            "2_look_ahead_continue: upcoming / upcoming_2 same type+identity / Page 2 of N → extend multi-page run",
            "3_look_ahead_type_change: upcoming different type → close run, start next",
        ],
        "compare_method": (
            "Use pages[i].window and adjacent pages' title_region/title_hint. "
            "A segment is a contiguous run. Never decide from current alone."
        ),
        "pages": page_rows,
        "blank_page_rule": (
            "Pages with is_blank=true are NOT documents. OMIT them from every segment "
            "(do not attach to previous or next). Never emit a blank-only segment."
        ),
        "heading_kinds": list(_HEADING_KINDS),
        "catalogue": _slim_catalogue(document_types),
    }
    return json.dumps(payload, default=str)


_INVOICE_FAMILY: frozenset[str] = frozenset(
    {"invoice", "tax_invoice", "commercial_invoice", "proforma"}
)


def _kinds_same_family(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return True
    if left == right:
        return True
    return left in _INVOICE_FAMILY and right in _INVOICE_FAMILY


def _effective_page_kind(text: str) -> HeadingKind | None:
    """Kind from title/body signals (ignores continuation short-circuit)."""
    receipt_kind = warehouse_receipt_kind_from_text(text or "")
    if receipt_kind:
        return receipt_kind
    signals = extract_document_heading_signals(text or "")
    return signals.primary_kind


def _clone_segment(
    template: PdfDocumentSegment,
    *,
    start_page: int,
    end_page: int,
    heading_kind: HeadingKind | None = None,
) -> PdfDocumentSegment:
    return PdfDocumentSegment(
        start_page=start_page,
        end_page=end_page,
        heading_kind=heading_kind if heading_kind is not None else template.heading_kind,
        boundary_confidence=template.boundary_confidence,
        page_kind_token=template.page_kind_token,
        identity_signature=template.identity_signature,
    )


def drop_blank_pages_from_segments(
    result: PdfSegmentResult,
    pages: list[PdfPageText],
) -> PdfSegmentResult:
    """Omit leading/trailing blanks; keep internal blanks inside a multi-page run.

    Internal blanks must NOT split one instrument (Page 1–N with a blank mid-run)
    into two segments — that causes over-split and same-role false duplicates.
    Blank-only segments are dropped entirely.
    """
    if not result.segments:
        return result

    cleaned: list[PdfDocumentSegment] = []
    changed = False
    for segment in sorted(result.segments, key=lambda s: s.start_page):
        first_nonblank: int | None = None
        last_nonblank: int | None = None
        for index in range(segment.start_page, segment.end_page + 1):
            if page_is_blank_for_segment(pages[index]):
                continue
            if first_nonblank is None:
                first_nonblank = index
            last_nonblank = index
        if first_nonblank is None or last_nonblank is None:
            changed = True
            continue
        if first_nonblank != segment.start_page or last_nonblank != segment.end_page:
            changed = True
        cleaned.append(
            _clone_segment(segment, start_page=first_nonblank, end_page=last_nonblank)
        )

    if not changed:
        return result

    logger.info(
        "pdf_segment_blank_pages_omitted",
        before=len(result.segments),
        after=len(cleaned),
    )
    method = result.segmentation_method
    if "blank" not in method:
        method = f"{method}+skipblank" if method else "skipblank"
    return PdfSegmentResult(
        segments=cleaned,
        detected_boundary_count=len(cleaned),
        segmentation_method=method,
        llm_reasoning=result.llm_reasoning,
        cap_exceeded=result.cap_exceeded,
    )


# Back-compat alias used by older tests/imports.
def merge_blank_only_segments(
    result: PdfSegmentResult,
    pages: list[PdfPageText],
) -> PdfSegmentResult:
    """Deprecated name: blanks are omitted, not merged into neighbors."""
    return drop_blank_pages_from_segments(result, pages)


def _should_merge_continuation(
    prev: PdfDocumentSegment,
    nxt: PdfDocumentSegment,
    pages: list[PdfPageText],
) -> bool:
    """True when nxt continues prev (Page X of Y / continuation), any doc type."""
    if nxt.start_page <= prev.end_page:
        return False
    # Allow a blank-only gap between segments (common after blank omission).
    if nxt.start_page != prev.end_page + 1:
        gap = range(prev.end_page + 1, nxt.start_page)
        if not gap or not all(page_is_blank_for_segment(pages[i]) for i in gap):
            return False

    next_page = pages[nxt.start_page]
    if page_is_blank_for_segment(next_page):
        return False

    prev_page = pages[prev.end_page]
    po_next = parse_page_of_marker(next_page.text or "")
    po_prev = parse_page_of_marker(prev_page.text or "")
    next_kind = _effective_page_kind(next_page.text or "") or nxt.heading_kind
    prev_kind = prev.heading_kind or _effective_page_kind(prev_page.text or "")

    # Completed Page N of N closes the prior run — never glue the next instrument,
    # even when the next visible page is a mid-run "Page 2 of N" of the same family
    # (orphan page-1 / OCR drop of the real page 1).
    if po_prev and po_prev[0] == po_prev[1]:
        return False

    if po_next and po_next[0] > 1:
        # Never glue across document families.
        if next_kind and prev_kind and not _kinds_same_family(prev_kind, next_kind):
            return False
        # Sequential Page X of Y within the same total → clear continuation.
        if po_prev and po_prev[1] == po_next[1] and po_next[0] >= po_prev[0] + 1:
            return True
        # Untyped / thin OCR continuation: only merge when page-of totals match
        # (or prev has no marker) AND kinds are compatible when both known.
        if next_kind and prev_kind and not _kinds_same_family(prev_kind, next_kind):
            return False
        if po_prev is None:
            # Previous page had no Page X of Y — do not assume a mid-page continues it
            # unless kinds clearly match the same family.
            return bool(next_kind and prev_kind and _kinds_same_family(prev_kind, next_kind))
        if po_prev[1] == po_next[1]:
            return not next_kind or not prev_kind or _kinds_same_family(prev_kind, next_kind)
        return False

    if is_continuation_page(next_page.text or ""):
        if (
            next_kind
            and prev_kind
            and not _kinds_same_family(prev_kind, next_kind)
        ):
            return False
        # Explicit "(CONTINUATION PAGE)" without page-of — require compatible kinds
        # when both sides are labeled.
        if next_kind and prev_kind:
            return _kinds_same_family(prev_kind, next_kind)
        return True

    return False


def _split_segments_on_type_changes(
    result: PdfSegmentResult,
    pages: list[PdfPageText],
) -> PdfSegmentResult:
    """Split runs that incorrectly glue different document types together."""
    from app.services.extraction.pdf_segment_service import _page_starts_new_document

    out: list[PdfDocumentSegment] = []
    changed = False
    for segment in sorted(result.segments, key=lambda s: s.start_page):
        open_kind = segment.heading_kind or _effective_page_kind(
            pages[segment.start_page].text or ""
        )
        run_start = segment.start_page
        for index in range(segment.start_page + 1, segment.end_page + 1):
            page = pages[index]
            if page_is_blank_for_segment(page):
                continue
            prev_page = pages[index - 1]
            po_prev = parse_page_of_marker(prev_page.text or "")
            prior_completed = bool(po_prev and po_prev[0] == po_prev[1])
            if is_continuation_page(page.text or "") and not prior_completed:
                cont_kind = _effective_page_kind(page.text or "")
                # Orphan mid-pack page (Page 2 of N) with a strong title that conflicts
                # with the open run must start a new segment — do not glue forever.
                if (
                    cont_kind
                    and open_kind
                    and not _kinds_same_family(open_kind, cont_kind)
                ):
                    changed = True
                    out.append(
                        _clone_segment(
                            segment,
                            start_page=run_start,
                            end_page=index - 1,
                            heading_kind=open_kind,
                        )
                    )
                    run_start = index
                    open_kind = cont_kind
                    continue
                if cont_kind and not open_kind:
                    open_kind = cont_kind
                continue
            page_kind = _effective_page_kind(page.text or "")
            starts_new = _page_starts_new_document(page, matchers=None)
            type_change = bool(
                page_kind and open_kind and not _kinds_same_family(open_kind, page_kind)
            )
            # Hard close after completed Page N of N when a new title/type appears.
            completed_then_new = bool(
                prior_completed and page_kind and (type_change or starts_new)
            )
            if not type_change and not completed_then_new:
                continue
            changed = True
            out.append(
                _clone_segment(
                    segment,
                    start_page=run_start,
                    end_page=index - 1,
                    heading_kind=open_kind,
                )
            )
            run_start = index
            open_kind = page_kind or open_kind
        out.append(
            _clone_segment(
                segment,
                start_page=run_start,
                end_page=segment.end_page,
                heading_kind=open_kind or segment.heading_kind,
            )
        )

    if not changed:
        return result
    return PdfSegmentResult(
        segments=out,
        detected_boundary_count=len(out),
        segmentation_method=result.segmentation_method,
        llm_reasoning=result.llm_reasoning,
        cap_exceeded=result.cap_exceeded,
    )


def _merge_continuation_segments(
    result: PdfSegmentResult,
    pages: list[PdfPageText],
) -> PdfSegmentResult:
    """Merge adjacent segments that are clearly one multi-page document."""
    ordered = sorted(result.segments, key=lambda s: s.start_page)
    if len(ordered) <= 1:
        return result

    merged: list[PdfDocumentSegment] = [ordered[0]]
    changed = False
    for nxt in ordered[1:]:
        prev = merged[-1]
        if _should_merge_continuation(prev, nxt, pages):
            changed = True
            merged[-1] = _clone_segment(
                prev,
                start_page=prev.start_page,
                end_page=nxt.end_page,
                heading_kind=prev.heading_kind or nxt.heading_kind,
            )
        else:
            merged.append(nxt)

    if not changed:
        return result
    logger.info(
        "pdf_segment_continuation_merged",
        before=len(result.segments),
        after=len(merged),
    )
    method = result.segmentation_method
    if "cont" not in method:
        method = f"{method}+cont" if method else "cont"
    return PdfSegmentResult(
        segments=merged,
        detected_boundary_count=len(merged),
        segmentation_method=method,
        llm_reasoning=result.llm_reasoning,
        cap_exceeded=result.cap_exceeded,
    )


def _page_is_non_document_orphan(text: str) -> bool:
    """True for disclaimer / T&Cs / empty scrap pages that must not become invoices.

    Conservative: only merge when the page is blank, matches known boilerplate
    markers, or is a near-empty OCR scrap with no document signals. Short but
    real pages (item receipts, LLM placeholder text, etc.) stay separate.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return True
    if is_continuation_page(cleaned):
        return False

    inferred = infer_page_document_kind_with_source(cleaned)
    if inferred is not None and inferred.source == "title_line":
        return False
    if (
        inferred is not None
        and inferred.source == "body_keyword"
        and inferred.kind not in _WEAK_STANDALONE_KINDS
    ):
        return False

    if bool(_AMOUNT_RE.search(cleaned)):
        return False
    identity = page_identity_signature(cleaned, page_kind_token=None) or ""
    if any(token in identity for token in _REF_IN_IDENTITY):
        return False

    lowered = " ".join(cleaned.lower().split())
    if any(marker in lowered for marker in _NON_DOCUMENT_MARKERS):
        # Weak mislabels like "statement" on a disclaimer page still orphan.
        return True

    # Near-empty OCR scrap only — do not glue ordinary short pages together.
    return inferred is None and len(cleaned) < 40


def _segment_is_non_document_orphan(
    segment: PdfDocumentSegment,
    pages: list[PdfPageText],
) -> bool:
    """True when every non-blank page in the segment is disclaimer/junk."""
    for index in range(segment.start_page, segment.end_page + 1):
        page = pages[index]
        if page_is_blank_for_segment(page):
            continue
        if not _page_is_non_document_orphan(page.text or ""):
            return False
    return True


def _adjacent_or_blank_gap(
    prev: PdfDocumentSegment,
    nxt: PdfDocumentSegment,
    pages: list[PdfPageText],
) -> bool:
    if nxt.start_page == prev.end_page + 1:
        return True
    if nxt.start_page <= prev.end_page:
        return False
    gap = range(prev.end_page + 1, nxt.start_page)
    return bool(gap) and all(page_is_blank_for_segment(pages[i]) for i in gap)


def merge_orphan_non_document_segments(
    result: PdfSegmentResult,
    pages: list[PdfPageText],
) -> PdfSegmentResult:
    """Attach disclaimer / structureless trailing pages to the previous segment.

    LLM and rules sometimes open a new segment on a T&Cs / disclaimer page that
    shares a weak body keyword with the prior form. Those pages must not become
    their own invoices (needs_rescan junk in the queue).
    """
    ordered = sorted(result.segments, key=lambda s: s.start_page)
    if len(ordered) <= 1:
        return result

    merged: list[PdfDocumentSegment] = [ordered[0]]
    changed = False
    for nxt in ordered[1:]:
        prev = merged[-1]
        if (
            _adjacent_or_blank_gap(prev, nxt, pages)
            and _segment_is_non_document_orphan(nxt, pages)
        ):
            changed = True
            merged[-1] = _clone_segment(
                prev,
                start_page=prev.start_page,
                end_page=nxt.end_page,
                heading_kind=prev.heading_kind or nxt.heading_kind,
            )
        else:
            merged.append(nxt)

    if not changed:
        return result
    logger.info(
        "pdf_segment_orphan_non_document_merged",
        before=len(result.segments),
        after=len(merged),
    )
    method = result.segmentation_method
    if "orphan" not in method:
        method = f"{method}+orphan" if method else "orphan"
    return PdfSegmentResult(
        segments=merged,
        detected_boundary_count=len(merged),
        segmentation_method=method,
        llm_reasoning=result.llm_reasoning,
        cap_exceeded=result.cap_exceeded,
    )


def _primary_identity_key(text: str, *, kind: str | None) -> str | None:
    """Compact primary ref for same-kind identity splits (invoice_no / bol / tracking)."""
    fields = page_identity_signature(
        text,
        page_kind_token=f"kind:{kind}" if kind else None,
    )
    if not fields:
        return None
    # Prefer document-number style keys over kind-only signatures.
    for prefix in ("invoice_no=", "bol_no=", "freight_order_no=", "tracking_no="):
        for part in fields.split("|"):
            if part.startswith(prefix) and len(part) > len(prefix):
                return part
    return None


def _split_same_kind_on_identity_change(
    result: PdfSegmentResult,
    pages: list[PdfPageText],
) -> PdfSegmentResult:
    """Split multi-page same-type runs when the primary instrument id changes.

    Covers consecutive Seagate invoices glued because type detection found no
    change, but invoice_no / BOL clearly differs on a non-continuation page.
    Skipped when the pack was already segment-capped (remainder is intentionally
    folded into the last segment).
    """
    if result.cap_exceeded:
        return result
    out: list[PdfDocumentSegment] = []
    changed = False
    for segment in sorted(result.segments, key=lambda s: s.start_page):
        if segment.end_page <= segment.start_page:
            out.append(segment)
            continue
        open_kind = segment.heading_kind or _effective_page_kind(
            pages[segment.start_page].text or ""
        )
        open_key = _primary_identity_key(pages[segment.start_page].text or "", kind=open_kind)
        run_start = segment.start_page
        for index in range(segment.start_page + 1, segment.end_page + 1):
            page = pages[index]
            if page_is_blank_for_segment(page):
                continue
            po = parse_page_of_marker(page.text or "")
            if po and po[0] > 1:
                # Mid Page-of-N — strengthen open key from this page when useful.
                page_key = _primary_identity_key(page.text or "", kind=open_kind)
                if page_key and not open_key:
                    open_key = page_key
                continue
            if is_continuation_page(page.text or ""):
                continue
            page_kind = _effective_page_kind(page.text or "") or open_kind
            if page_kind and open_kind and not _kinds_same_family(open_kind, page_kind):
                continue  # type splitter owns this
            page_key = _primary_identity_key(page.text or "", kind=page_kind or open_kind)
            if open_key and page_key and page_key != open_key:
                changed = True
                out.append(
                    _clone_segment(
                        segment,
                        start_page=run_start,
                        end_page=index - 1,
                        heading_kind=open_kind,
                    )
                )
                run_start = index
                open_kind = page_kind or open_kind
                open_key = page_key
                continue
            if page_key and not open_key:
                open_key = page_key
            if page_kind:
                open_kind = page_kind
        out.append(
            _clone_segment(
                segment,
                start_page=run_start,
                end_page=segment.end_page,
                heading_kind=open_kind or segment.heading_kind,
            )
        )

    if not changed:
        return result
    logger.info(
        "pdf_segment_identity_split",
        before=len(result.segments),
        after=len(out),
    )
    method = result.segmentation_method
    if "ident" not in method:
        method = f"{method}+ident" if method else "ident"
    return PdfSegmentResult(
        segments=out,
        detected_boundary_count=len(out),
        segmentation_method=method,
        llm_reasoning=result.llm_reasoning,
        cap_exceeded=result.cap_exceeded,
    )


def refine_segment_boundaries(
    result: PdfSegmentResult,
    pages: list[PdfPageText],
) -> PdfSegmentResult:
    """Fix oversplits/mis-glues, omit blanks, re-merge Page-of-N, relabel kinds."""
    refined = _split_segments_on_type_changes(result, pages)
    # Drop blanks before continuation merge so blank-only gaps can be bridged.
    refined = drop_blank_pages_from_segments(refined, pages)
    refined = _merge_continuation_segments(refined, pages)
    # Disclaimer / structureless pages must attach to the prior instrument.
    refined = merge_orphan_non_document_segments(refined, pages)
    refined = _split_same_kind_on_identity_change(refined, pages)
    return _relabel_segments_from_page_text(refined, pages)


# Prefer the public name; keep old alias for callers/tests.
refine_llm_segments = refine_segment_boundaries


def _relabel_segments_from_page_text(
    result: PdfSegmentResult,
    pages: list[PdfPageText],
) -> PdfSegmentResult:
    """Set heading_kind from the first non-blank page text (fixes BOL-on-invoice mislabels)."""
    relabeled: list[PdfDocumentSegment] = []
    changed = False
    for segment in result.segments:
        kind = segment.heading_kind
        kind_token = segment.page_kind_token
        for index in range(segment.start_page, segment.end_page + 1):
            if page_is_blank_for_segment(pages[index]):
                continue
            if is_continuation_page(pages[index].text or ""):
                # Prefer the opening page of a Page X of Y run for labeling.
                if kind is not None:
                    break
            page_kind = _effective_page_kind(pages[index].text or "")
            if page_kind:
                if page_kind != kind:
                    changed = True
                kind = page_kind
                kind_token = f"kind:{page_kind}"
            break
        relabeled.append(
            PdfDocumentSegment(
                start_page=segment.start_page,
                end_page=segment.end_page,
                heading_kind=kind,
                boundary_confidence=segment.boundary_confidence,
                page_kind_token=kind_token,
                identity_signature=segment.identity_signature,
            )
        )
    if not changed:
        return result
    return PdfSegmentResult(
        segments=relabeled,
        detected_boundary_count=len(relabeled),
        segmentation_method=result.segmentation_method,
        llm_reasoning=result.llm_reasoning,
        cap_exceeded=result.cap_exceeded,
    )


def _parse_llm_segments(
    raw: dict[str, Any],
    *,
    pages: list[PdfPageText],
    document_types: list[DocumentTypeDefinition] | None,
    custom_field_keys: list[str] | None,
    max_segments: int,
) -> PdfSegmentResult | None:
    rows = raw.get("segments")
    if not isinstance(rows, list) or not rows:
        return None

    page_count = len(pages)
    covered = [False] * page_count
    segments: list[PdfDocumentSegment] = []

    for row in rows:
        if not isinstance(row, dict):
            return None
        try:
            start = int(row.get("start_page"))
            end = int(row.get("end_page"))
        except (TypeError, ValueError):
            return None
        if start < 0 or end < start or end >= page_count:
            return None

        heading_kind = _normalize_heading_kind(str(row.get("heading_kind") or ""))
        suggested_dt = str(row.get("suggested_dt") or "").strip().upper() or None
        if heading_kind is None and suggested_dt and document_types:
            heading_kind = heading_kind_from_token(  # type: ignore[assignment]
                f"dt:{suggested_dt}",
                document_types=document_types,
            )

        try:
            confidence = float(row.get("confidence", 0.85))
        except (TypeError, ValueError):
            confidence = 0.85
        confidence = max(0.0, min(1.0, confidence))

        kind_token = _page_kind_token_from_llm(heading_kind, suggested_dt)
        start_text = pages[start].text if start < len(pages) else ""
        identity = page_identity_signature(
            start_text,
            page_kind_token=kind_token,
            custom_field_keys=custom_field_keys,
        )

        for index in range(start, end + 1):
            if covered[index]:
                return None
            covered[index] = True

        segments.append(
            PdfDocumentSegment(
                start_page=start,
                end_page=end,
                heading_kind=heading_kind,
                boundary_confidence=confidence,
                page_kind_token=kind_token,
                identity_signature=identity,
            )
        )

    # Non-blank pages must be covered; blanks may be omitted or present (stripped later).
    for index, page in enumerate(pages):
        if page_is_blank_for_segment(page):
            continue
        if not covered[index]:
            return None

    if len(segments) > max_segments:
        return None

    reasoning = str(raw.get("reasoning") or "").strip()
    parsed = PdfSegmentResult(
        segments=segments,
        detected_boundary_count=len(segments),
        segmentation_method="llm",
        llm_reasoning=reasoning or None,
    )
    return refine_llm_segments(parsed, pages)


async def segment_pdf_pages_via_llm(
    pages: list[PdfPageText],
    *,
    document_types: list[DocumentTypeDefinition] | None = None,
    custom_field_keys: list[str] | None = None,
    max_segments: int = 20,
) -> PdfSegmentResult | None:
    """One batched LLM call to detect page boundaries. Returns None on failure."""
    if len(pages) <= 1:
        return None

    settings = get_settings()
    if not settings.pdf_segment_llm_enabled or not settings.runtime_llm_available:
        return None

    user = build_segment_llm_user_payload(pages, document_types=document_types or [])
    raw = await chat_json_async(
        system=resolve_system_prompt_text("pdf.segment.system"),
        user=user,
        timeout_seconds=settings.pdf_segment_llm_timeout_seconds,
        require_runtime=True,
    )
    if raw is None:
        logger.info("pdf_segment_llm_unavailable")
        return None

    result = _parse_llm_segments(
        raw,
        pages=pages,
        document_types=document_types,
        custom_field_keys=custom_field_keys,
        max_segments=max_segments,
    )
    if result is None:
        logger.warning("pdf_segment_llm_invalid_response")
        return None

    logger.info(
        "pdf_segment_llm_ok",
        segments=len(result.segments),
        prompt_version=settings.pdf_segment_llm_prompt_version,
    )
    return result


async def segment_pdf_pages_smart(
    pages: list[PdfPageText],
    *,
    max_segments: int = 20,
    document_types: list[DocumentTypeDefinition] | None = None,
    custom_field_keys: list[str] | None = None,
    catalogue_matchers: list[CataloguePageMatcher] | None = None,
) -> PdfSegmentResult:
    """LLM-first segmentation; rules only when LLM is unavailable or fails."""
    from app.services.extraction.azure_openai_throttle import azure_openai_cooling_down

    settings = get_settings()
    llm_eligible = (
        len(pages) > 1
        and settings.pdf_segment_llm_enabled
        and settings.runtime_llm_available
        and not azure_openai_cooling_down("chat")
    )

    llm_result: PdfSegmentResult | None = None
    if llm_eligible:
        llm_result = await segment_pdf_pages_via_llm(
            pages,
            document_types=document_types,
            custom_field_keys=custom_field_keys,
            max_segments=max_segments,
        )
        if llm_result is not None and llm_result.segments:
            return llm_result
        if azure_openai_cooling_down("chat"):
            logger.info("pdf_segment_llm_skipped_circuit_open")
        else:
            logger.info("pdf_segment_llm_fallback")
    elif azure_openai_cooling_down("chat"):
        logger.info("pdf_segment_llm_skipped_circuit_open")
    else:
        logger.info(
            "pdf_segment_llm_ineligible",
            pages=len(pages),
            enabled=settings.pdf_segment_llm_enabled,
            runtime_available=settings.runtime_llm_available,
        )

    rules_result = segment_pdf_pages(
        pages,
        max_segments=max_segments,
        document_types=document_types,
        custom_field_keys=custom_field_keys,
        catalogue_matchers=catalogue_matchers,
    )
    return refine_segment_boundaries(
        PdfSegmentResult(
            segments=rules_result.segments,
            detected_boundary_count=rules_result.detected_boundary_count,
            segmentation_method="rules",
            llm_reasoning=llm_result.llm_reasoning if llm_result else None,
            cap_exceeded=rules_result.cap_exceeded,
        ),
        pages,
    )
