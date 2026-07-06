"""Tests for LLM-based PDF page segmentation."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.services.extraction.pdf_page_text_service import PdfPageText
from app.services.extraction.pdf_segment_llm_service import (
    _parse_llm_segments,
    build_segment_llm_user_payload,
    segment_pdf_pages_smart,
    segment_pdf_pages_via_llm,
)


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
async def test_segment_smart_uses_llm_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
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
    pages = [_page(0, "TAX INVOICE\nINV-1")]
    payload = build_segment_llm_user_payload(pages, document_types=[])
    assert '"page_index": 0' in payload
    assert "TAX INVOICE" in payload
    assert "heading_kinds" in payload
