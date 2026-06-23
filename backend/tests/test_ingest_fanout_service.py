"""Tests for multi-document PDF upload fan-out."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.audit import AuditLog
from app.models.invoice import Invoice
from app.services.ingest_fanout_service import ingest_upload_file
from app.services.pdf_page_text_service import PdfPageText
from app.services.pdf_split_service import extract_pdf_page_range_bytes, segment_upload_filename


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
async def test_ingest_upload_single_pdf_unchanged(db_session: AsyncSession) -> None:
    from app.models.tenant import Tenant

    org = Tenant(name="Test Org", slug="test-org")
    db_session.add(org)
    await db_session.flush()

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
        "app.services.ingest_fanout_service.extract_pdf_page_texts",
        lambda _path: pages,
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
        "app.services.ingest_fanout_service.extract_pdf_page_texts",
        lambda _path: pages,
    )
    monkeypatch.setattr(
        "app.services.ingest_fanout_service.extract_pdf_page_range_bytes",
        lambda _path, start, end: f"%PDF-part-{start}-{end}".encode(),
    )

    files = {"file": ("combo.pdf", b"%PDF combo", "application/pdf")}
    res = await client.post("/api/invoices/upload?defer_processing=true", files=files)
    assert res.status_code == 200
    body = res.json()
    assert body["meta"]["segment_count"] == 2
    assert len(body["meta"]["segment_invoice_ids"]) == 2
