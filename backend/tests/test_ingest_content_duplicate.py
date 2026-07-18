"""Content-fingerprint duplicate detection across bundle segments and standalone uploads."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.services.extraction.pdf_content_fingerprint import compute_pdf_content_fingerprint
from app.services.extraction.pdf_page_text_service import PdfPageText, PdfPageTextExtraction
from app.services.ingest.ingest_fanout_service import ingest_upload_file
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.fixture(autouse=True)
def _enable_pdf_split(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PDF_MULTI_DOCUMENT_SPLIT", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _invoice_page_text() -> str:
    return "TAX INVOICE\nInvoice No: INV-CONTENT-1\nTotal $99.00\nVendor: Acme"


@pytest.mark.asyncio
async def test_standalone_upload_matches_prior_bundle_segment_fingerprint(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoice_text = _invoice_page_text()
    fingerprint = compute_pdf_content_fingerprint(
        [PdfPageText(0, invoice_text)],
        0,
        0,
    )
    assert fingerprint is not None

    existing = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="bundle-segment-hash",
        content_fingerprint=fingerprint,
        invoice_no="INV-CONTENT-1",
        vendor="Acme",
    )
    db_session.add(existing)
    await db_session.flush()

    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.extract_pdf_page_texts",
        lambda _path: PdfPageTextExtraction(pages=[PdfPageText(0, invoice_text)]),
    )
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.store_invoice_pdf",
        lambda *args, **kwargs: "uploads/standalone.pdf",
    )

    result = await ingest_upload_file(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="hv-org",
        tenant_name="High Volt Analytics",
        filename="invoice-alone.pdf",
        data=b"%PDF standalone different bytes",
        purchase_document_type=None,
    )
    await db_session.flush()

    assert result.duplicate_handled is True
    assert len(result.invoice_ids) == 1
    shadow = await db_session.get(Invoice, result.invoice_ids[0])
    assert shadow is not None
    assert shadow.status == InvoiceStatus.DUPLICATE_SKIPPED
    assert shadow.file_hash is None

    rows = (await db_session.execute(select(Invoice))).scalars().all()
    assert len(rows) == 2

@pytest.mark.asyncio
async def test_bundle_reupload_detected_via_source_file_hash(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_hash = "ryans-bundle-hash-001"
    existing = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.VALIDATING,
        currency="AUD",
        file_hash="segment-one-hash",
        content_fingerprint="fp-invoice-segment",
        extracted_fields={"source_file_hash": bundle_hash},
        invoice_no="250970286",
        vendor="Spectra Innovations",
    )
    db_session.add(existing)
    await db_session.flush()

    monkeypatch.setenv("PDF_MULTI_DOCUMENT_SPLIT", "true")
    get_settings.cache_clear()

    async def _fake_config(_session, _tenant_id):
        return type("Cfg", (), {"document_types": []})()

    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.load_config_for_tenant",
        _fake_config,
    )
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.extract_pdf_page_texts",
        lambda _path: PdfPageTextExtraction(
            pages=[
                PdfPageText(0, "COMMERCIAL INVOICE\nInvoice No: 250970286"),
                PdfPageText(1, "PACKING LIST\nInvoice No: 250970286"),
            ]
        ),
    )
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.extract_pdf_page_range_bytes",
        lambda _path, start, end: f"%PDF-part-{start}-{end}".encode(),
    )
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.store_invoice_pdf",
        lambda *args, **kwargs: "uploads/segment.pdf",
    )
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.compute_sha256_bytes",
        lambda data: bundle_hash if data == b"%PDF bundle" else f"seg-{data!r}".encode()[:16].hex(),
    )

    result = await ingest_upload_file(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="hv-org",
        tenant_name="High Volt Analytics",
        filename="bundle.pdf",
        data=b"%PDF bundle",
        purchase_document_type=None,
    )
    await db_session.flush()

    assert result.duplicate_handled is True
    assert len(result.invoice_ids) <= 1


@pytest.mark.asyncio
async def test_bundle_reupload_matches_prior_source_file_hash(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whole-file re-upload finds a prior segment via source_file_hash."""
    existing = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="standalone-hash",
        content_fingerprint="fp-standalone",
        invoice_no="INV-CONTENT-1",
        vendor="Acme",
        extracted_fields={"source_file_hash": "bundle-parent-hash"},
    )
    db_session.add(existing)
    await db_session.flush()

    pages = [
        PdfPageText(0, "PURCHASE ORDER\nPO Number: PO-500\n"),
        PdfPageText(1, _invoice_page_text()),
    ]
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.extract_pdf_page_texts",
        lambda _path: PdfPageTextExtraction(pages=pages),
    )
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.store_invoice_pdf",
        lambda *args, **kwargs: "uploads/bundle.pdf",
    )

    async def _fake_config(_session, _tenant_id):
        return type("Cfg", (), {"document_types": []})()

    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.load_config_for_tenant",
        _fake_config,
    )
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.compute_sha256_bytes",
        lambda data: "bundle-parent-hash",
    )

    result = await ingest_upload_file(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="hv-org",
        tenant_name="High Volt Analytics",
        filename="bundle.pdf",
        data=b"%PDF bundle",
        purchase_document_type=None,
    )
    await db_session.flush()

    assert result.segment_count == 2
    assert result.duplicate_handled is True

    rows = (await db_session.execute(select(Invoice))).scalars().all()
    assert any(r.status == InvoiceStatus.PROCESSED for r in rows)
    assert any(
        (r.extracted_fields or {}).get("source_file_hash") == "bundle-parent-hash"
        for r in rows
    )
