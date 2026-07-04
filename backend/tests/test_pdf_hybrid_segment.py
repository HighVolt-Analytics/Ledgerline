"""Hybrid OCR page text and bundle source-hash dedup."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.dossier.document_duplicate_service import find_existing_ingest_duplicate
from app.services.extraction.pdf_page_text_service import PdfPageText, _merge_thin_pages_with_di
from app.services.extraction.pdf_segment_service import segment_pdf_pages
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

    merged = _merge_thin_pages_with_di(pages, pdf_path)
    assert "PACKING LIST" in merged[1].text

    segments = segment_pdf_pages(merged)
    assert len(segments) == 3
    assert segments[0].heading_kind == "commercial_invoice"
    assert segments[1].heading_kind == "packing_list"
    assert segments[2].heading_kind == "customs_permit"


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
    segments = segment_pdf_pages(pages)
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
