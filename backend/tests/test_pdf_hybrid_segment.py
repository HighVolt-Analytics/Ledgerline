"""Hybrid OCR page text and bundle source-hash dedup."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.services.dossier.document_duplicate_service import find_existing_ingest_duplicate
from app.services.extraction.pdf_page_text_service import (
    PdfPageText,
    PdfPageTextExtraction,
    _merge_thin_pages_with_di,
    extract_pdf_page_texts,
)
from app.services.extraction.pdf_segment_service import segment_pdf_pages
from app.services.ingest.ingest_fanout_service import ingest_upload_file
from app.tenant_ids import TESTING_TENANT_UUID


def test_merge_thin_pages_upgrades_empty_middle_page(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    pdf_path = tmp_path / "bundle.pdf"
    pdf_path.write_bytes(b"%PDF")

    pages = [
        PdfPageText(0, "COMMERCIAL INVOICE\nInvoice No: SYN-900"),
        PdfPageText(1, ""),
        PdfPageText(2, "CARGO CLEARANCE PERMIT\nPERMIT NO: PER900"),
    ]

    monkeypatch.setattr(
        "app.services.extraction.pdf_page_text_service.read_pdf_page_texts_via_di",
        lambda _path: [
            (0, pages[0].text),
            (1, "PACKING LIST\nInvoice No: SYN-900"),
            (2, pages[2].text),
        ],
    )

    merged, incomplete = _merge_thin_pages_with_di(pages, pdf_path)
    assert incomplete == ()
    assert "PACKING LIST" in merged[1].text

    segments = segment_pdf_pages(merged).segments
    assert len(segments) == 3
    assert segments[0].heading_kind == "commercial_invoice"
    assert segments[1].heading_kind == "packing_list"
    assert segments[2].heading_kind == "customs_permit"


def test_import_bundle_text_plus_scanned_pages_splits_four_ways() -> None:
    """Invoice + scanned PL + permit block + scanned transport (pattern-based)."""
    pages = [
        PdfPageText(0, "COMMERCIAL INVOICE\nInvoice No: EXP-9001\nTotal USD 500"),
        PdfPageText(1, "PACKING LIST / WEIGHT LIST\nInvoice No: EXP-9001"),
        PdfPageText(2, "CARGO CLEARANCE PERMIT\nPERMIT NO: PER9001"),
        PdfPageText(3, "PERMIT NO: PER9001\n(CONTINUATION PAGE)\nLine items"),
        PdfPageText(4, "PERMIT NO: PER9001\n(CONTINUATION PAGE)\nDeclarant"),
        PdfPageText(
            5,
            "603 SIN 70364626\nShipper's Name and Address\nACME EXPORTS PTE LTD",
        ),
        PdfPageText(6, "ATTACHED COPY\nDESCRIPTION OF GOODS: PARTS"),
    ]
    segments = segment_pdf_pages(pages).segments
    assert len(segments) == 4
    assert segments[0].heading_kind == "commercial_invoice"
    assert segments[1].heading_kind == "packing_list"
    assert segments[2].heading_kind == "customs_permit"
    assert segments[2].end_page == 4
    assert segments[3].heading_kind == "transport_doc"
    assert segments[3].start_page == 5


def test_no_kind_short_garbage_page_needs_di_upgrade() -> None:
    from app.services.extraction.pdf_page_text_service import _page_needs_di_upgrade

    assert _page_needs_di_upgrade("") is True
    assert _page_needs_di_upgrade("GIM25090026 $ SPECTRA Spectra Innovations Pte Ltd") is True
    assert _page_needs_di_upgrade("PACKING LIST\nInvoice No: SYN-900") is False
    assert _page_needs_di_upgrade("PERMIT NO: OD5I458006S\n(CONTINUATION PAGE)\nLine items") is False


def test_full_di_fallback_splits_when_hybrid_missed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    pdf_path = tmp_path / "bundle.pdf"
    pdf_path.write_bytes(b"%PDF")

    local_pages = [
        PdfPageText(0, "COMMERCIAL INVOICE\nInvoice No: SYN-900"),
        PdfPageText(1, ""),
        PdfPageText(2, "CARGO CLEARANCE PERMIT\nPERMIT NO: PER900"),
    ]
    full_di_pages = [
        (0, local_pages[0].text),
        (1, "PACKING LIST\nInvoice No: SYN-900"),
        (2, local_pages[2].text),
    ]

    monkeypatch.setattr(
        "app.services.extraction.pdf_page_text_service._extract_local_page_texts",
        lambda _path: local_pages,
    )
    monkeypatch.setattr(
        "app.services.extraction.pdf_page_text_service.read_pdf_page_texts_via_di",
        lambda _path: full_di_pages,
    )

    extraction = extract_pdf_page_texts(pdf_path)
    assert len(extraction.pages) == 3
    assert "PACKING LIST" in extraction.pages[1].text

    segments = segment_pdf_pages(extraction.pages).segments
    assert len(segments) == 3


def test_scanned_middle_page_splits_after_di_upgrade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    pdf_path = tmp_path / "bundle.pdf"
    pdf_path.write_bytes(b"%PDF")

    pages = [
        PdfPageText(0, "TAX INVOICE\nInvoice No: INV-42\nTotal $100"),
        PdfPageText(1, ""),
    ]
    monkeypatch.setattr(
        "app.services.extraction.pdf_page_text_service.read_pdf_page_texts_via_di",
        lambda _path: [
            (0, pages[0].text),
            (1, "PACKING LIST\nInvoice No: INV-42"),
        ],
    )

    merged, _ = _merge_thin_pages_with_di(pages, pdf_path)
    segments = segment_pdf_pages(merged).segments
    assert len(segments) == 2
    assert segments[0].heading_kind == "tax_invoice"
    assert segments[1].heading_kind == "packing_list"


def test_transport_doc_splits_from_permit_block() -> None:
    pages = [
        PdfPageText(0, "CARGO CLEARANCE PERMIT\nPERMIT NO: OD5I458006S"),
        PdfPageText(1, "PERMIT NO: OD5I458006S\n(CONTINUATION PAGE)\nLine items"),
        PdfPageText(
            2,
            "603 SIN 70364626\nShipper's Name and Address\nSPECTRA INNOVATIONS PTE LTD",
        ),
        PdfPageText(3, "ATTACHED COPY\nDESCRIPTION OF GOODS: COMPUTER PARTS"),
    ]
    segments = segment_pdf_pages(pages).segments
    assert len(segments) == 2
    assert segments[0].heading_kind == "customs_permit"
    assert segments[0].end_page == 1
    assert segments[1].heading_kind == "transport_doc"
    assert segments[1].start_page == 2


@pytest.mark.asyncio
async def test_find_existing_ingest_duplicate_matches_bundle_source_hash(
    db_session: AsyncSession,
) -> None:
    bundle_hash = "bundle-parent-hash-abc"
    existing = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="segment-hash-only",
        extracted_fields={"source_file_hash": bundle_hash},
        vendor="Synth Vendor",
    )
    db_session.add(existing)
    await db_session.flush()

    found = await find_existing_ingest_duplicate(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        file_hash=bundle_hash,
    )
    assert found is not None
    assert found.id == existing.id


@pytest.mark.asyncio
async def test_ingest_fanout_import_bundle_pattern(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org = Tenant(name="Import Org", slug="import-org")
    db_session.add(org)
    await db_session.flush()

    pages = [
        PdfPageText(0, "COMMERCIAL INVOICE\nInvoice No: EXP-100\nTotal USD 100"),
        PdfPageText(1, "PACKING LIST\nInvoice No: EXP-100"),
        PdfPageText(2, "CARGO CLEARANCE PERMIT\nPERMIT NO: PER100"),
        PdfPageText(3, "PERMIT NO: PER100\n(CONTINUATION PAGE)\nDetails"),
        PdfPageText(4, "HAWB NO: AWB100\nShipper's Name and Address\nACME"),
    ]

    import fitz

    source = tmp_path / "import_bundle.pdf"
    doc = fitz.open()
    for page in pages:
        sheet = doc.new_page()
        sheet.insert_text((72, 72), page.text.replace("\n", " "))
    doc.save(source)
    doc.close()
    data = source.read_bytes()

    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.extract_pdf_page_texts",
        lambda _path: PdfPageTextExtraction(pages=pages),
    )
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.store_invoice_pdf",
        lambda *args, **kwargs: "uploads/segment.pdf",
    )

    result = await ingest_upload_file(
        db_session,
        tenant_id=org.id,
        tenant_slug=org.slug,
        tenant_name=org.name,
        filename="import_bundle.pdf",
        data=data,
        purchase_document_type=None,
    )
    await db_session.flush()

    assert result.segment_count == 4
    assert len(result.invoice_ids) == 4

    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event == "pdf_segmented")
        )
    ).scalars().all()
    assert len(audit) == 4


@pytest.mark.asyncio
async def test_ingest_logs_segment_cap_exceeded_skip(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org = Tenant(name="Cap Org", slug="cap-org")
    db_session.add(org)
    await db_session.flush()

    pages = [
        PdfPageText(i, f"TAX INVOICE\nInvoice No: INV-{i}\nTotal $10")
        for i in range(25)
    ]
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.extract_pdf_page_texts",
        lambda _path: PdfPageTextExtraction(pages=pages),
    )
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.store_invoice_pdf",
        lambda *args, **kwargs: "uploads/one.pdf",
    )
    monkeypatch.setenv("PDF_SEGMENT_MAX_SEGMENTS", "5")
    from app.config import get_settings

    get_settings.cache_clear()

    result = await ingest_upload_file(
        db_session,
        tenant_id=org.id,
        tenant_slug=org.slug,
        tenant_name=org.name,
        filename="many_invoices.pdf",
        data=b"%PDF cap test",
        purchase_document_type=None,
    )
    await db_session.flush()

    get_settings.cache_clear()
    assert result.segment_count == 1
    assert len(result.invoice_ids) == 1

    skipped = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event == "pdf_split_skipped")
        )
    ).scalars().all()
    assert len(skipped) == 1
    assert skipped[0].detail["reason"] == "segment_cap_exceeded"
    assert skipped[0].detail["segment_count_detected"] == 25


@pytest.mark.asyncio
async def test_ingest_logs_ocr_incomplete_but_still_splits(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org = Tenant(name="OCR Org", slug="ocr-org")
    db_session.add(org)
    await db_session.flush()

    pages = [
        PdfPageText(0, "COMMERCIAL INVOICE\nInvoice No: OCR-1\nTotal $50"),
        PdfPageText(1, "PACKING LIST\nInvoice No: OCR-1"),
        PdfPageText(2, "CARGO CLEARANCE PERMIT\nPERMIT NO: OCRP1"),
    ]

    import fitz

    source = tmp_path / "ocr_bundle.pdf"
    doc = fitz.open()
    for page in pages:
        sheet = doc.new_page()
        sheet.insert_text((72, 72), page.text.replace("\n", " "))
    doc.save(source)
    doc.close()

    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.extract_pdf_page_texts",
        lambda _path: PdfPageTextExtraction(pages=pages, incomplete_ocr_indices=(1,)),
    )
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.store_invoice_pdf",
        lambda *args, **kwargs: "uploads/segment.pdf",
    )

    result = await ingest_upload_file(
        db_session,
        tenant_id=org.id,
        tenant_slug=org.slug,
        tenant_name=org.name,
        filename="ocr_bundle.pdf",
        data=source.read_bytes(),
        purchase_document_type=None,
    )
    await db_session.flush()

    assert result.segment_count == 3
    assert len(result.invoice_ids) == 3

    skipped = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event == "pdf_split_skipped")
        )
    ).scalars().all()
    assert len(skipped) == 1
    assert skipped[0].detail["reason"] == "ocr_incomplete"
    assert skipped[0].detail["thin_page_count"] == 1
