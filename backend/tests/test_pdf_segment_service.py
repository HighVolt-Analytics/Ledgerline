"""Tests for deterministic PDF page segmentation."""

from app.services.extraction.pdf_page_text_service import PdfPageText
from app.services.extraction.pdf_segment_service import (
    purchase_document_type_from_heading,
    segment_pdf_pages,
)


def _page(index: int, text: str) -> PdfPageText:
    return PdfPageText(page_index=index, text=text)


def _segments(pages, **kwargs):
    return segment_pdf_pages(pages, **kwargs).segments


def test_single_page_is_one_segment() -> None:
    pages = [_page(0, "TAX INVOICE\nInvoice No: INV-1\nTotal $100")]
    segments = _segments(pages)
    assert len(segments) == 1
    assert segments[0].start_page == 0
    assert segments[0].end_page == 0
    assert segments[0].heading_kind == "tax_invoice"


def test_multi_page_single_invoice_is_one_segment() -> None:
    pages = [
        _page(0, "TAX INVOICE\nInvoice No: INV-1"),
        _page(1, "Line items\nWidget $50"),
    ]
    segments = _segments(pages)
    assert len(segments) == 1
    assert segments[0].end_page == 1


def test_repeated_header_same_invoice_stays_one_segment() -> None:
    pages = [
        _page(0, "TAX INVOICE\nInvoice No: INV-1\nTotal $100"),
        _page(1, "TAX INVOICE\nInvoice No: INV-1\nLine items"),
    ]
    segments = _segments(pages)
    assert len(segments) == 1
    assert segments[0].end_page == 1


def test_po_grn_invoice_bundle_splits_with_abbreviated_grn() -> None:
    pages = [
        _page(0, "PURCHASE ORDER\nPO Number: PO-9001\nVendor: Acme"),
        _page(1, "GRN\nPO 9001\nReceived qty 10"),
        _page(2, "TAX INVOICE\nInvoice No: INV-9001\nTotal $110.00"),
    ]
    segments = _segments(pages)
    assert len(segments) == 3
    assert segments[1].heading_kind == "grn"


def test_po_grn_invoice_bundle_splits_three_ways() -> None:
    pages = [
        _page(0, "PURCHASE ORDER\nPO Number: PO-9001\nVendor: Acme"),
        _page(1, "GOODS RECEIPT NOTE\nPO 9001\nReceived qty 10"),
        _page(2, "TAX INVOICE\nInvoice No: INV-9001\nTotal $110.00"),
    ]
    segments = _segments(pages)
    assert len(segments) == 3
    assert segments[0].heading_kind == "purchase_order"
    assert segments[1].heading_kind == "grn"
    assert segments[2].heading_kind == "tax_invoice"
    assert segments[0].end_page == 0
    assert segments[1].start_page == 1
    assert segments[2].start_page == 2


def test_two_invoices_same_kind_split_on_invoice_number() -> None:
    pages = [
        _page(0, "TAX INVOICE\nInvoice No: INV-A\nTotal $10"),
        _page(1, "TAX INVOICE\nInvoice No: INV-B\nTotal $20"),
    ]
    segments = _segments(pages)
    assert len(segments) == 2
    assert segments[0].end_page == 0
    assert segments[1].start_page == 1


def test_blank_page_between_docs_is_omitted() -> None:
    """Blank pages are skipped — not attached to the previous document."""
    pages = [
        _page(0, "TAX INVOICE\nInvoice No: INV-1\nTotal $100"),
        _page(1, ""),
        _page(2, "PACKING LIST\nInvoice No: INV-1\nCartons 4"),
    ]
    segments = _segments(pages)
    assert len(segments) == 2
    assert segments[0].start_page == 0
    assert segments[0].end_page == 0
    assert segments[0].heading_kind == "tax_invoice"
    assert segments[1].start_page == 2
    assert segments[1].heading_kind == "packing_list"


def test_intentionally_blank_marker_is_omitted() -> None:
    pages = [
        _page(0, "COMMERCIAL INVOICE\nInvoice No: CI-9"),
        _page(1, "THIS PAGE INTENTIONALLY LEFT BLANK"),
        _page(2, "HAWB NO: ABC123\nShipper"),
    ]
    segments = _segments(pages)
    assert len(segments) == 2
    assert segments[0].end_page == 0
    assert segments[1].start_page == 2
    assert segments[1].heading_kind == "transport_doc"


def test_page_of_n_keeps_multi_page_invoice_together() -> None:
    pages = [
        _page(0, "INVOICE\nInvoice No: 9300667281\nPage : 1 of 3"),
        _page(1, "INVOICE 9300667281\nPage : 2 of 3\nItem 30"),
        _page(2, "INVOICE 9300667281\nPage : 3 of 3\nTotal Value"),
        _page(3, "PACKING LIST\nPage : 1 of 2\nBill of Lading 9064907291"),
    ]
    segments = _segments(pages)
    assert len(segments) == 2
    assert segments[0].start_page == 0
    assert segments[0].end_page == 2
    assert segments[0].heading_kind in {"invoice", "tax_invoice", "commercial_invoice"}
    assert segments[1].start_page == 3
    assert segments[1].heading_kind == "packing_list"


def test_multi_page_invoice_then_packing_list_look_ahead() -> None:
    """Look-ahead type change: close invoice run before packing list."""
    pages = [
        _page(0, "TAX INVOICE\nInvoice No: INV-42\nPage 1 of 2"),
        _page(1, "TAX INVOICE\nInvoice No: INV-42\nTotals and bank details"),
        _page(2, "PACKING LIST\nInvoice No: INV-42"),
    ]
    segments = _segments(pages)
    assert len(segments) == 2
    assert segments[0].start_page == 0
    assert segments[0].end_page == 1
    assert segments[0].heading_kind == "tax_invoice"
    assert segments[1].start_page == 2
    assert segments[1].heading_kind == "packing_list"


def test_purchase_document_type_from_heading() -> None:
    assert purchase_document_type_from_heading("purchase_order") == "po"
    assert purchase_document_type_from_heading("grn") == "grn"
    assert purchase_document_type_from_heading("tax_invoice") == "invoice"
    assert purchase_document_type_from_heading("commercial_invoice") == "invoice"
    assert purchase_document_type_from_heading("packing_list") is None


def test_import_dossier_page_kinds_segment() -> None:
    pages = [
        _page(0, "COMMERCIAL INVOICE\nInvoice No: 260671582\nTotal USD 1000"),
        _page(1, "PACKING LIST / WEIGHT LIST\nInvoice No: 260671582"),
        _page(2, "CERTIFICATE OF ORIGIN\nInvoice No: 260671582"),
        _page(3, "HAWB NO: UAF2606064\nShipper details"),
        _page(4, "CARGO CLEARANCE PERMIT\nPERMIT NO: OD6F444404Y"),
        _page(5, "PERMIT NO: OD6F444404Y\n(CONTINUATION PAGE)\nLine items"),
    ]
    segments = _segments(pages)
    assert len(segments) == 5
    assert segments[0].heading_kind == "commercial_invoice"
    assert segments[1].heading_kind == "packing_list"
    assert segments[2].heading_kind == "certificate_of_origin"
    assert segments[3].heading_kind == "transport_doc"
    assert segments[4].heading_kind == "customs_permit"
    assert segments[4].end_page == 5


def test_segment_cap_exceeded_collapses_to_single_segment() -> None:
    pages = [
        _page(i, f"TAX INVOICE\nInvoice No: INV-{i}\nTotal $10")
        for i in range(25)
    ]
    result = segment_pdf_pages(pages, max_segments=5)
    assert result.cap_exceeded is True
    assert result.detected_boundary_count == 25
    assert len(result.segments) == 1
