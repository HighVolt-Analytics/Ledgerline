"""Tests for deterministic PDF page segmentation."""

from app.services.extraction.pdf_page_text_service import PdfPageText
from app.services.extraction.pdf_segment_service import (
    purchase_document_type_from_heading,
    segment_pdf_pages,
)


def _page(index: int, text: str) -> PdfPageText:
    return PdfPageText(page_index=index, text=text)


def test_single_page_is_one_segment() -> None:
    pages = [_page(0, "TAX INVOICE\nInvoice No: INV-1\nTotal $100")]
    segments = segment_pdf_pages(pages)
    assert len(segments) == 1
    assert segments[0].start_page == 0
    assert segments[0].end_page == 0
    assert segments[0].heading_kind == "tax_invoice"


def test_multi_page_single_invoice_is_one_segment() -> None:
    pages = [
        _page(0, "TAX INVOICE\nInvoice No: INV-1"),
        _page(1, "Line items\nWidget $50"),
    ]
    segments = segment_pdf_pages(pages)
    assert len(segments) == 1
    assert segments[0].end_page == 1


def test_repeated_header_same_invoice_stays_one_segment() -> None:
    pages = [
        _page(0, "TAX INVOICE\nInvoice No: INV-1\nTotal $100"),
        _page(1, "TAX INVOICE\nInvoice No: INV-1\nLine items"),
    ]
    segments = segment_pdf_pages(pages)
    assert len(segments) == 1
    assert segments[0].end_page == 1


def test_po_grn_invoice_bundle_splits_with_abbreviated_grn() -> None:
    pages = [
        _page(0, "PURCHASE ORDER\nPO Number: PO-9001\nVendor: Acme"),
        _page(1, "GRN\nPO 9001\nReceived qty 10"),
        _page(2, "TAX INVOICE\nInvoice No: INV-9001\nTotal $110.00"),
    ]
    segments = segment_pdf_pages(pages)
    assert len(segments) == 3
    assert segments[1].heading_kind == "grn"


def test_po_grn_invoice_bundle_splits_three_ways() -> None:
    pages = [
        _page(0, "PURCHASE ORDER\nPO Number: PO-9001\nVendor: Acme"),
        _page(1, "GOODS RECEIPT NOTE\nPO 9001\nReceived qty 10"),
        _page(2, "TAX INVOICE\nInvoice No: INV-9001\nTotal $110.00"),
    ]
    segments = segment_pdf_pages(pages)
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
    segments = segment_pdf_pages(pages)
    assert len(segments) == 2
    assert segments[0].end_page == 0
    assert segments[1].start_page == 1


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
    segments = segment_pdf_pages(pages)
    assert len(segments) == 5
    assert segments[0].heading_kind == "commercial_invoice"
    assert segments[1].heading_kind == "packing_list"
    assert segments[2].heading_kind == "certificate_of_origin"
    assert segments[3].heading_kind == "transport_doc"
    assert segments[4].heading_kind == "customs_permit"
    assert segments[4].end_page == 5
