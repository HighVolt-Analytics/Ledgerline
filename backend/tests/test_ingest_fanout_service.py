"""Tests for multi-document PDF upload fan-out."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.services.ingest.ingest_fanout_service import (
    IngestSourceMetadata,
    ingest_file_with_fanout,
    ingest_upload_file,
)
from app.services.extraction.pdf_page_text_service import PdfPageText, PdfPageTextExtraction
from app.services.extraction.pdf_split_service import extract_pdf_page_range_bytes, segment_upload_filename


@pytest.fixture(autouse=True)
def _enable_pdf_split(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PDF_MULTI_DOCUMENT_SPLIT", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_segment_upload_filename() -> None:
    assert segment_upload_filename("bundle.pdf", 0, 3) == "bundle__part1of3.pdf"
    assert segment_upload_filename("bundle.pdf", 0, 1) == "bundle.pdf"


def test_extract_pdf_page_range_bytes(tmp_path) -> None:
    import fitz

    source = tmp_path / "source.pdf"
    doc = fitz.open()
    for label in ("PAGE-1", "PAGE-2"):
        page = doc.new_page()
        page.insert_text((72, 72), label)
    doc.save(source)
    doc.close()

    payload = extract_pdf_page_range_bytes(source, 0, 0)
    assert payload.startswith(b"%PDF")

    out = tmp_path / "slice.pdf"
    out.write_bytes(payload)
    text = fitz.open(out)[0].get_text()
    assert "PAGE-1" in text
    assert "PAGE-2" not in text


@pytest.mark.asyncio
async def test_ingest_upload_single_pdf_unchanged(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.tenant import Tenant

    org = Tenant(name="Test Org", slug="test-org")
    db_session.add(org)
    await db_session.flush()

    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.store_invoice_pdf",
        lambda *args, **kwargs: "uploads/one.pdf",
    )

    data = b"%PDF-1.4 single-doc"
    result = await ingest_upload_file(
        db_session,
        tenant_id=org.id,
        tenant_slug=org.slug,
        tenant_name=org.name,
        filename="one.pdf",
        data=data,
        purchase_document_type=None,
    )
    assert result.segment_count == 1
    assert len(result.invoice_ids) == 1


@pytest.mark.asyncio
async def test_ingest_upload_fanout_from_segmented_pdf(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.tenant import Tenant

    org = Tenant(name="Fanout Org", slug="fanout-org")
    db_session.add(org)
    await db_session.flush()

    pages = [
        PdfPageText(0, "PURCHASE ORDER\nPO Number: PO-100\n"),
        PdfPageText(1, "GOODS RECEIPT NOTE\nPO 100\n"),
        PdfPageText(2, "TAX INVOICE\nInvoice No: INV-100\nTotal $50\n"),
    ]

    import fitz

    source = tmp_path / "bundle.pdf"
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
        filename="bundle.pdf",
        data=data,
        purchase_document_type=None,
    )
    await db_session.flush()

    assert result.segment_count == 3
    assert len(result.invoice_ids) == 3

    rows = (
        await db_session.execute(select(Invoice).where(Invoice.tenant_id == org.id))
    ).scalars().all()
    assert len(rows) == 3
    assert len({row.file_hash for row in rows}) == 3

    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.event == "pdf_segmented")
        )
    ).scalars().all()
    assert len(audit) == 3


@pytest.mark.asyncio
async def test_upload_api_returns_segment_meta(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [
        PdfPageText(0, "PURCHASE ORDER\nPO Number: PO-200\n"),
        PdfPageText(1, "TAX INVOICE\nInvoice No: INV-200\nTotal $10\n"),
    ]
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.extract_pdf_page_texts",
        lambda _path: PdfPageTextExtraction(pages=pages),
    )
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.store_invoice_pdf",
        lambda *args, **kwargs: "uploads/segment.pdf",
    )
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.extract_pdf_page_range_bytes",
        lambda _path, start, end: f"%PDF-part-{start}-{end}".encode(),
    )
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.store_invoice_pdf",
        lambda *args, **kwargs: "uploads/segment.pdf",
    )

    files = {"file": ("combo.pdf", b"%PDF combo", "application/pdf")}
    res = await client.post("/api/invoices/upload?defer_processing=true", files=files)
    assert res.status_code == 200
    body = res.json()
    assert body["meta"]["segment_count"] == 2
    assert len(body["meta"]["segment_invoice_ids"]) == 2


@pytest.mark.asyncio
async def test_ingest_file_with_fanout_applies_source_metadata(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.tenant import Tenant

    org = Tenant(name="Meta Org", slug="meta-org")
    db_session.add(org)
    await db_session.flush()

    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.store_invoice_pdf",
        lambda *args, **kwargs: "uploads/channel.pdf",
    )
    async def _allow_channel(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(
        "app.services.credit_service.assert_can_ingest_via_channel",
        _allow_channel,
    )

    result = await ingest_file_with_fanout(
        db_session,
        tenant_id=org.id,
        tenant_slug=org.slug,
        tenant_name=org.name,
        filename="receipt.pdf",
        data=b"%PDF channel",
        source=IngestSourceMetadata(
            storage_vendor_slug="acme",
            email_sender="+61400111222",
            email_subject="Expense",
            email_message_id="wa-msg-1",
            email_attachment_name="receipt.pdf",
            capture_source="whatsapp",
            matched_rule_ids='["ingest:whatsapp"]',
        ),
    )
    assert result.segment_count == 1
    inv = await db_session.get(Invoice, result.invoice_ids[0])
    assert inv is not None
    assert inv.capture_source == "whatsapp"
    assert inv.email_sender == "+61400111222"
    assert inv.storage_vendor_slug == "acme"


@pytest.mark.asyncio
async def test_ingest_sets_so_reference_from_filename(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.tenant import Tenant

    org = Tenant(name="Sales Org", slug="sales-org")
    db_session.add(org)
    await db_session.flush()

    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.store_invoice_pdf",
        lambda *args, **kwargs: "uploads/sales_order_SO-1001.pdf",
    )

    result = await ingest_file_with_fanout(
        db_session,
        tenant_id=org.id,
        tenant_slug=org.slug,
        tenant_name=org.name,
        filename="sales_order_SO-1001.pdf",
        data=b"%PDF sales",
        source=IngestSourceMetadata(
            email_attachment_name="sales_order_SO-1001.pdf",
            capture_source="upload",
        ),
    )
    inv = await db_session.get(Invoice, result.invoice_ids[0])
    assert inv is not None
    assert inv.so_reference == "SO-1001"


@pytest.mark.asyncio
async def test_load_segment_heading_kind_from_pdf_segmented_audit(
    db_session: AsyncSession,
) -> None:
    from app.models.tenant import Tenant
    from app.services.audit.audit_service import log_event
    from app.services.classification.segment_heading_classification import load_segment_heading_kind_from_audit

    org = Tenant(name="Audit Org", slug="audit-org")
    db_session.add(org)
    await db_session.flush()

    inv = Invoice(
        tenant_id=org.id,
        status=InvoiceStatus.PENDING,
        currency="AUD",
        file_hash="seg-audit-hash",
    )
    db_session.add(inv)
    await db_session.flush()

    await log_event(
        db_session,
        "pdf_segmented",
        invoice_id=inv.id,
        detail={"heading_kind": "purchase_order", "segment_index": 0},
    )
    await db_session.flush()

    kind = await load_segment_heading_kind_from_audit(db_session, inv.id)
    assert kind == "purchase_order"


@pytest.mark.asyncio
async def test_multi_segment_ignores_purchase_document_type_param(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.tenant import Tenant

    org = Tenant(name="Type Org", slug="type-org")
    db_session.add(org)
    await db_session.flush()

    pages = [
        PdfPageText(0, "PURCHASE ORDER\nPO Number: PO-300\n"),
        PdfPageText(1, "TAX INVOICE\nInvoice No: INV-300\nTotal $10\n"),
    ]
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.extract_pdf_page_texts",
        lambda _path: PdfPageTextExtraction(pages=pages),
    )
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.extract_pdf_page_range_bytes",
        lambda _path, start, end: f"%PDF-part-{start}-{end}".encode(),
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
        filename="bundle.pdf",
        data=b"%PDF bundle",
        purchase_document_type="invoice",
    )
    await db_session.flush()

    assert result.segment_count == 2
    rows = (
        await db_session.execute(
            select(Invoice).where(Invoice.id.in_(result.invoice_ids)).order_by(Invoice.id)
        )
    ).scalars().all()
    assert rows[0].purchase_document_type == "po"
    assert rows[1].purchase_document_type == "invoice"
