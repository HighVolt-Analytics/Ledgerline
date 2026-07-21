"""Tests for LLM-based PDF page segmentation."""

from __future__ import annotations

import json

import pytest

from app.config import get_settings
from app.services.extraction.pdf_page_text_service import PdfPageText
from app.services.extraction.pdf_segment_llm_service import (
    _parse_llm_segments,
    build_segment_llm_user_payload,
    segment_pdf_pages_smart,
    segment_pdf_pages_via_llm,
)
from app.services.extraction.pdf_segment_service import PdfDocumentSegment, PdfSegmentResult


def _page(index: int, text: str) -> PdfPageText:
    return PdfPageText(page_index=index, text=text)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _llm_segments_response(pages: list[PdfPageText], *, kinds: list[str]) -> dict:
    segments = []
    for index, kind in enumerate(kinds):
        segments.append(
            {
                "start_page": index,
                "end_page": index,
                "heading_kind": kind,
                "suggested_dt": "",
                "document_label": kind.replace("_", " ").title(),
                "confidence": 0.9,
            }
        )
    return {"segments": segments, "reasoning": "Split on document type headings."}


@pytest.mark.asyncio
async def test_segment_via_llm_splits_item_receipt_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        _page(0, "PURCHASE ORDER\nPO Number: PO-9001\nVendor: Acme"),
        _page(1, "COMMERCIAL INVOICE\nInvoice No: INV-9001\nTotal $110.00"),
        _page(2, "PACKING LIST\nInvoice No: INV-9001"),
        _page(3, "HAWB NO: ABC123\nShipper details"),
        _page(4, "Item Receipt\nPO 9001\nReceived qty 10"),
    ]
    response = _llm_segments_response(
        pages,
        kinds=["purchase_order", "commercial_invoice", "packing_list", "transport_doc", "grn"],
    )

    async def _fake_chat_json_async(**kwargs):
        return response

    monkeypatch.setenv("PDF_SEGMENT_LLM_ENABLED", "true")
    monkeypatch.setenv("RUNTIME_LLM_ENABLED", "true")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "app.services.extraction.pdf_segment_llm_service.chat_json_async",
        _fake_chat_json_async,
    )

    result = await segment_pdf_pages_via_llm(pages)
    assert result is not None
    assert result.segmentation_method == "llm"
    assert len(result.segments) == 5
    assert result.segments[4].heading_kind == "grn"
    assert result.llm_reasoning == "Split on document type headings."


@pytest.mark.asyncio
async def test_segment_smart_prefers_llm_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [
        _page(0, "PURCHASE ORDER\nPO Number: PO-1"),
        _page(1, "GRN\nReceived qty 5"),
    ]
    response = _llm_segments_response(pages, kinds=["purchase_order", "grn"])

    async def _fake_chat_json_async(**kwargs):
        return response

    monkeypatch.setenv("PDF_SEGMENT_LLM_ENABLED", "true")
    monkeypatch.setenv("RUNTIME_LLM_ENABLED", "true")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "app.services.extraction.pdf_segment_llm_service.chat_json_async",
        _fake_chat_json_async,
    )

    result = await segment_pdf_pages_smart(pages)
    assert result.segmentation_method == "llm"
    assert len(result.segments) == 2
    assert result.segments[0].heading_kind == "purchase_order"
    assert result.segments[1].heading_kind == "grn"


@pytest.mark.asyncio
async def test_segment_smart_uses_llm_even_when_rules_would_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Rules can already split; LLM must still run and win when it succeeds.
    pages = [
        _page(0, "x" * 40),
        _page(1, "y" * 40),
    ]
    response = _llm_segments_response(pages, kinds=["commercial_invoice", "packing_list"])

    async def _fake_chat_json_async(**kwargs):
        return response

    monkeypatch.setenv("PDF_SEGMENT_LLM_ENABLED", "true")
    monkeypatch.setenv("RUNTIME_LLM_ENABLED", "true")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "app.services.extraction.pdf_segment_llm_service.chat_json_async",
        _fake_chat_json_async,
    )
    monkeypatch.setattr(
        "app.services.extraction.pdf_segment_llm_service.segment_pdf_pages",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("rules must not run when LLM succeeds")),
    )

    result = await segment_pdf_pages_smart(pages)
    assert result.segmentation_method == "llm"
    assert len(result.segments) == 2


@pytest.mark.asyncio
async def test_segment_smart_falls_back_to_rules_when_llm_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [
        _page(0, "PURCHASE ORDER\nPO Number: PO-9001"),
        _page(1, "GRN\nPO 9001\nReceived qty 10"),
    ]
    monkeypatch.setenv("PDF_SEGMENT_LLM_ENABLED", "false")

    result = await segment_pdf_pages_smart(pages)
    assert result.segmentation_method == "rules"
    assert len(result.segments) == 2


@pytest.mark.asyncio
async def test_segment_smart_falls_back_on_invalid_llm_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [
        _page(0, "PURCHASE ORDER\nPO Number: PO-9001"),
        _page(1, "GRN\nPO 9001\nReceived qty 10"),
    ]

    async def _bad_chat_json_async(**kwargs):
        return {"segments": [{"start_page": 0, "end_page": 0, "heading_kind": "purchase_order"}]}

    monkeypatch.setenv("PDF_SEGMENT_LLM_ENABLED", "true")
    monkeypatch.setenv("RUNTIME_LLM_ENABLED", "true")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "app.services.extraction.pdf_segment_llm_service.chat_json_async",
        _bad_chat_json_async,
    )

    result = await segment_pdf_pages_smart(pages)
    assert result.segmentation_method == "rules"
    assert len(result.segments) == 2


def test_parse_llm_segments_rejects_non_contiguous_coverage() -> None:
    pages = [_page(0, "PO"), _page(1, "GRN")]
    raw = {
        "segments": [
            {"start_page": 0, "end_page": 0, "heading_kind": "purchase_order", "confidence": 0.9},
        ],
        "reasoning": "Incomplete",
    }
    assert _parse_llm_segments(raw, pages=pages, document_types=None, custom_field_keys=None, max_segments=20) is None


def test_build_segment_llm_user_payload_includes_page_excerpts() -> None:
    pages = [_page(0, "TAX INVOICE\nINV-1"), _page(1, ""), _page(2, "PACKING LIST\nINV-1")]
    payload = build_segment_llm_user_payload(pages, document_types=[])
    assert '"page_index": 0' in payload
    assert "TAX INVOICE" in payload
    assert "heading_kinds" in payload
    assert '"is_blank": true' in payload
    assert "blank_page_rule" in payload
    assert "compare_method" in payload
    assert "decision_order" in payload
    data = json.loads(payload)
    window1 = data["pages"][1]["window"]
    assert window1["previous"]["page_index"] == 0
    assert window1["upcoming"]["page_index"] == 2
    assert window1["upcoming_2"] is None
    assert data["pages"][0]["window"]["previous"] is None
    assert data["pages"][0]["window"]["upcoming_2"]["page_index"] == 2
    assert "TAX INVOICE" in window1["previous"]["title_region"]
    assert "PACKING LIST" in window1["upcoming"]["title_region"]


def test_drop_blank_pages_omits_instead_of_merging() -> None:
    from app.services.extraction.pdf_segment_llm_service import drop_blank_pages_from_segments

    pages = [
        _page(0, "TAX INVOICE\nINV-1"),
        _page(1, ""),
        _page(2, "PACKING LIST\nINV-1"),
    ]
    raw = PdfSegmentResult(
        segments=[
            PdfDocumentSegment(0, 0, "tax_invoice", 0.9),
            PdfDocumentSegment(1, 1, None, 0.5),
            PdfDocumentSegment(2, 2, "packing_list", 0.9),
        ],
        detected_boundary_count=3,
        segmentation_method="llm",
    )
    cleaned = drop_blank_pages_from_segments(raw, pages)
    assert len(cleaned.segments) == 2
    assert cleaned.segments[0].start_page == 0
    assert cleaned.segments[0].end_page == 0
    assert cleaned.segments[0].heading_kind == "tax_invoice"
    assert cleaned.segments[1].start_page == 2
    assert cleaned.segments[1].end_page == 2
    assert "skipblank" in cleaned.segmentation_method


def test_refine_splits_completed_page_of_one_then_new_title() -> None:
    from app.services.extraction.pdf_segment_llm_service import refine_llm_segments

    pages = [
        _page(0, "TAX INVOICE\nInvoice No: 6000000299\nPage 1 of 1"),
        _page(1, "PACKING LIST\nInvoice No: 6000000299\nPage 1 of 1"),
        _page(2, "Delivery Note\nDO.No : RPPL/DO/102\nPO#: 260643048"),
        _page(3, ""),
    ]
    # LLM wrongly glued invoice + packing list (shared invoice number).
    raw = PdfSegmentResult(
        segments=[
            PdfDocumentSegment(0, 1, "invoice", 0.9),
            PdfDocumentSegment(2, 2, "grn", 0.9),
        ],
        detected_boundary_count=2,
        segmentation_method="llm",
    )
    refined = refine_llm_segments(raw, pages)
    assert [(s.start_page, s.end_page, s.heading_kind) for s in refined.segments] == [
        (0, 0, "tax_invoice"),
        (1, 1, "packing_list"),
        (2, 2, "grn"),
    ]


def test_refine_merges_page_of_n_oversplit_and_splits_type_glue() -> None:
    from app.services.extraction.pdf_segment_llm_service import refine_llm_segments

    pages = [
        _page(0, "INVOICE\nInvoice No: 9300667281\nPage : 1 of 3"),
        _page(1, "INVOICE 9300667281\nPage : 2 of 3\nItem 30"),
        _page(2, "INVOICE 9300667281\nPage : 3 of 3\nTotals"),
        _page(3, "PACKING LIST\nPage : 1 of 2\nFreight Order 6101746071"),
        _page(4, "PACKING LIST\nPage : 2 of 2\nForwarder Instructions"),
    ]
    # Simulate bad LLM: invoice page1 alone, pages 2-3 mislabeled transport,
    # then packing page1 glued with a phantom, packing page2 alone — and
    # invoice page3 glued with packing page1.
    raw = PdfSegmentResult(
        segments=[
            PdfDocumentSegment(0, 0, "invoice", 0.9),
            PdfDocumentSegment(1, 1, "transport_doc", 0.9),
            PdfDocumentSegment(2, 3, "transport_doc", 0.9),  # invoice 3/3 + packing 1/2
            PdfDocumentSegment(4, 4, "packing_list", 0.9),
        ],
        detected_boundary_count=4,
        segmentation_method="llm",
    )
    refined = refine_llm_segments(raw, pages)
    assert len(refined.segments) == 2
    assert refined.segments[0].start_page == 0
    assert refined.segments[0].end_page == 2
    assert refined.segments[0].heading_kind == "invoice"
    assert refined.segments[1].start_page == 3
    assert refined.segments[1].end_page == 4
    assert refined.segments[1].heading_kind == "packing_list"


@pytest.mark.asyncio
async def test_rules_path_uses_refine_and_keeps_invoice_despite_bol_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [
        _page(
            0,
            "INVOICE COMPUTER GENERATED DOCUMENT\nInvoice No: 9300667417\n"
            "Page : 1 of 2\nBill of Lading No: 9064997073",
        ),
        _page(
            1,
            "INVOICE 9300667417 COMPUTER GENERATED DOCUMENT\nPage : 2 of 2\nTotals",
        ),
        _page(
            2,
            "PACKING LIST\nPage : 1 of 2\nBill of Lading No: 9064997073",
        ),
        _page(3, "PACKING LIST\nPage : 2 of 2\nForwarder Instructions"),
        _page(4, "Air Freight Services\nHAWB NO: 9064997073\nShipper details"),
    ]
    monkeypatch.setenv("PDF_SEGMENT_LLM_ENABLED", "false")
    result = await segment_pdf_pages_smart(pages)
    assert result.segmentation_method.startswith("rules")
    assert len(result.segments) == 3
    assert result.segments[0].start_page == 0
    assert result.segments[0].end_page == 1
    assert result.segments[0].heading_kind == "invoice"
    assert result.segments[1].start_page == 2
    assert result.segments[1].end_page == 3
    assert result.segments[1].heading_kind == "packing_list"
    assert result.segments[2].start_page == 4
    assert result.segments[2].heading_kind == "transport_doc"


@pytest.mark.asyncio
async def test_rules_path_splits_awb_from_seagate_invoice_without_title_word(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AWB must not glue to the next Seagate invoice whose page-1 omits 'INVOICE'."""
    pages = [
        _page(
            0,
            "Not Negotiable Air Waybill\nAir Freight Services\n"
            "HAWB NO. 9064907291\nShipper's Name and Address\nSEAGATE",
        ),
        _page(
            1,
            "SEAGATE\nSHIPPING ORGANIZATION\nSeagate Technology (Thailand) Ltd.\n"
            "SELLING ORGANIZATION\nSeagate Singapore\n"
            "Page : 1 of 2\nBILL OF LADING NO\n9064997073\n"
            "Item\nMaterial Number\nUnit Price\nTotal Price\n",
        ),
        _page(
            2,
            "Page : 2 of 2\nINVOICE 9300667417\nCOMPUTER GENERATED DOCUMENT\n"
            "Total Value(in USD) : 48400\n",
        ),
        _page(
            3,
            "PACKING LIST\nPage : 1 of 2\nBILL OF LADING NO\n9064997073\n"
            "Top Level Handling Unit\nNumber of Cartons : 16\n",
        ),
        _page(4, "PACKING LIST\nPage : 2 of 2\nForwarder Instructions"),
    ]
    monkeypatch.setenv("PDF_SEGMENT_LLM_ENABLED", "false")
    result = await segment_pdf_pages_smart(pages)
    assert result.segmentation_method.startswith("rules")
    kinds = [(s.start_page, s.end_page, s.heading_kind) for s in result.segments]
    assert kinds == [
        (0, 0, "transport_doc"),
        (1, 2, "invoice"),
        (3, 4, "packing_list"),
    ]


def test_refine_does_not_merge_awb_with_invoice_page_of_n() -> None:
    from app.services.extraction.pdf_segment_llm_service import refine_llm_segments

    pages = [
        _page(0, "Air Freight Services\nHAWB NO: 9064907291\nShipper details"),
        _page(
            1,
            "SEAGATE\nSHIPPING ORGANIZATION\nPage : 1 of 2\n"
            "BILL OF LADING NO 9064997073\nMaterial Number\nUnit Price\nTotal Price",
        ),
        _page(2, "Page : 2 of 2\nINVOICE 9300667417\nTotals"),
    ]
    # Bad LLM: one transport run covering AWB + both invoice pages.
    raw = PdfSegmentResult(
        segments=[PdfDocumentSegment(0, 2, "transport_doc", 0.9)],
        detected_boundary_count=1,
        segmentation_method="llm",
    )
    refined = refine_llm_segments(raw, pages)
    assert [(s.start_page, s.end_page, s.heading_kind) for s in refined.segments] == [
        (0, 0, "transport_doc"),
        (1, 2, "invoice"),
    ]


def test_parse_llm_segments_allows_omitted_blanks() -> None:
    pages = [
        _page(0, "TAX INVOICE\nINV-1"),
        _page(1, ""),
        _page(2, "PACKING LIST\nINV-1"),
    ]
    raw = {
        "segments": [
            {"start_page": 0, "end_page": 0, "heading_kind": "tax_invoice", "confidence": 0.9},
            {"start_page": 2, "end_page": 2, "heading_kind": "packing_list", "confidence": 0.9},
        ],
        "reasoning": "Blank omitted",
    }
    result = _parse_llm_segments(
        raw, pages=pages, document_types=None, custom_field_keys=None, max_segments=20
    )
    assert result is not None
    assert len(result.segments) == 2
    assert result.segments[0].end_page == 0
    assert result.segments[1].start_page == 2


def test_internal_blank_does_not_split_multipage_invoice() -> None:
    from app.services.extraction.pdf_segment_llm_service import refine_llm_segments

    pages = [
        _page(0, "INVOICE\nInvoice No: 9300667281\nPage : 1 of 3"),
        _page(1, ""),  # internal blank mid-run
        _page(2, "INVOICE 9300667281\nPage : 3 of 3\nTotals"),
        _page(3, "PACKING LIST\nPage : 1 of 1\nBill of Lading No: 9064907291"),
    ]
    raw = PdfSegmentResult(
        segments=[PdfDocumentSegment(0, 3, "invoice", 0.9)],
        detected_boundary_count=1,
        segmentation_method="llm",
    )
    refined = refine_llm_segments(raw, pages)
    kinds = [(s.start_page, s.end_page, s.heading_kind) for s in refined.segments]
    assert kinds == [
        (0, 2, "invoice"),  # blank kept inside range; not split into two invoices
        (3, 3, "packing_list"),
    ]


def test_thin_page_of_two_after_awb_does_not_glue() -> None:
    from app.services.extraction.pdf_segment_llm_service import refine_llm_segments

    pages = [
        _page(0, "Air Freight Services\nHAWB NO: 9064907291\nShipper details"),
        _page(1, "Page : 2 of 2\n"),  # thin OCR, no kind
    ]
    raw = PdfSegmentResult(
        segments=[
            PdfDocumentSegment(0, 0, "transport_doc", 0.9),
            PdfDocumentSegment(1, 1, None, 0.5),
        ],
        detected_boundary_count=2,
        segmentation_method="llm",
    )
    refined = refine_llm_segments(raw, pages)
    # Untyped Page 2 of 2 must not glue onto an AWB that had no page-of marker.
    assert len(refined.segments) == 2
    assert refined.segments[0].heading_kind == "transport_doc"
    assert refined.segments[0].end_page == 0


def test_orphan_page_two_of_n_with_invoice_title_starts_new_segment() -> None:
    from app.services.extraction.pdf_segment_llm_service import refine_llm_segments

    pages = [
        _page(0, "Air Freight Services\nHAWB NO: AAA111\nShipper details"),
        _page(1, "Page : 2 of 2\nINVOICE 9300667417\nCOMPUTER GENERATED DOCUMENT\nTotals"),
    ]
    raw = PdfSegmentResult(
        segments=[PdfDocumentSegment(0, 1, "transport_doc", 0.9)],
        detected_boundary_count=1,
        segmentation_method="llm",
    )
    refined = refine_llm_segments(raw, pages)
    assert [(s.start_page, s.end_page, s.heading_kind) for s in refined.segments] == [
        (0, 0, "transport_doc"),
        (1, 1, "invoice"),
    ]


def test_same_kind_identity_split_consecutive_invoices() -> None:
    from app.services.extraction.pdf_segment_llm_service import refine_llm_segments

    pages = [
        _page(0, "INVOICE\nInvoice No: 9300667281\nPage : 1 of 1\nUnit Price\nTotal Price"),
        _page(1, "INVOICE\nInvoice No: 9300667417\nPage : 1 of 1\nUnit Price\nTotal Price"),
    ]
    raw = PdfSegmentResult(
        segments=[PdfDocumentSegment(0, 1, "invoice", 0.9)],
        detected_boundary_count=1,
        segmentation_method="llm",
    )
    refined = refine_llm_segments(raw, pages)
    assert [(s.start_page, s.end_page, s.heading_kind) for s in refined.segments] == [
        (0, 0, "invoice"),
        (1, 1, "invoice"),
    ]


def test_body_invoice_no_field_does_not_make_packing_list_an_invoice() -> None:
    from app.services.extraction.document_heading_utils import infer_page_document_kind

    text = (
        "Top Level Handling Unit\nNumber of Cartons : 5\n"
        "Invoice No: 9300667281\nBill of Lading No: 9064907291\n"
    )
    assert infer_page_document_kind(text) == "packing_list"
