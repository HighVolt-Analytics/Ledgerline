"""LLM-based PDF page boundary detection (batched, prompt-only)."""

from __future__ import annotations

import json
from typing import Any, Sequence

from app.config import get_settings
from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.catalogue_page_signals import (
    CataloguePageMatcher,
    heading_kind_from_token,
)
from app.services.extraction.azure_openai_client import chat_json_async
from app.services.extraction.document_heading_utils import HeadingKind
from app.services.extraction.document_identity_service import page_identity_signature
from app.services.extraction.llm_catalogue_rows import build_llm_catalogue_rows
from app.services.extraction.pdf_page_text_service import PdfPageText
from app.services.extraction.pdf_segment_service import (
    PdfDocumentSegment,
    PdfSegmentResult,
    segment_pdf_pages,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_PAGE_EXCERPT_MAX = 1500

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

_SEGMENT_LLM_SYSTEM = """You group PDF pages into separate logical finance/logistics documents.
Return JSON only with keys: segments, reasoning.

Each segment object must have:
- start_page (0-indexed inclusive integer)
- end_page (0-indexed inclusive integer)
- heading_kind (one of the allowed heading_kinds list, or empty string if unsure)
- suggested_dt (tenant catalogue code from catalogue, or empty string)
- document_label (short human-readable label for the document)
- confidence (0.0-1.0 for this segment boundary)

Rules:
- segments must be contiguous, non-overlapping, and cover every input page exactly once.
- Group continuation pages with their parent document (multi-page customs permits, AWB attached copies, invoice continuation pages).
- heading_kind "grn" includes goods receipt notes, GRN, item receipts, inventory receipts, delivery notes, and material receipts.
- heading_kind "transport_doc" includes air waybills, house waybills (HAWB), master air waybills, and bills of lading.
- heading_kind "customs_permit" includes cargo clearance permits and customs entry documents.
- Use suggested_dt from the tenant catalogue when a row clearly matches the page content; otherwise leave suggested_dt empty.
- Base decisions only on the provided page text excerpts; do not invent documents or page ranges.
- reasoning is one short sentence summarizing how you split the bundle."""


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


def build_segment_llm_user_payload(
    pages: list[PdfPageText],
    *,
    document_types: Sequence[DocumentTypeDefinition] | None,
) -> str:
    payload = {
        "page_count": len(pages),
        "pages": [
            {
                "page_index": page.page_index,
                "text_excerpt": (page.text or "")[:_PAGE_EXCERPT_MAX],
            }
            for page in pages
        ],
        "heading_kinds": list(_HEADING_KINDS),
        "catalogue": build_llm_catalogue_rows(document_types or []),
    }
    return json.dumps(payload, default=str)


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

    if not all(covered) or len(segments) > max_segments:
        return None

    reasoning = str(raw.get("reasoning") or "").strip()
    return PdfSegmentResult(
        segments=segments,
        detected_boundary_count=len(segments),
        segmentation_method="llm",
        llm_reasoning=reasoning or None,
    )


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
        system=_SEGMENT_LLM_SYSTEM,
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
    """LLM-primary segmentation with rule-based fallback."""
    settings = get_settings()
    llm_eligible = (
        len(pages) > 1
        and settings.pdf_segment_llm_enabled
        and settings.runtime_llm_available
    )

    if llm_eligible:
        llm_result = await segment_pdf_pages_via_llm(
            pages,
            document_types=document_types,
            custom_field_keys=custom_field_keys,
            max_segments=max_segments,
        )
        if llm_result is not None and len(llm_result.segments) > 1:
            return llm_result
        if llm_result is not None and len(llm_result.segments) == 1:
            logger.info("pdf_segment_llm_single_segment_fallback_rules")
        else:
            logger.info("pdf_segment_llm_fallback")

    rules_result = segment_pdf_pages(
        pages,
        max_segments=max_segments,
        document_types=document_types,
        custom_field_keys=custom_field_keys,
        catalogue_matchers=catalogue_matchers,
    )
    return PdfSegmentResult(
        segments=rules_result.segments,
        cap_exceeded=rules_result.cap_exceeded,
        detected_boundary_count=rules_result.detected_boundary_count,
        segmentation_method="rules",
        llm_reasoning=rules_result.llm_reasoning,
    )
