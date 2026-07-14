"""Layer 1 — exact match: identical file bytes / exact invoice_no+vendor.

Runs with fuzzy and content-similarity flags off (defaults / explicit disable).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.services.dossier.document_duplicate_service import (
    evaluate_file_hash_duplicate,
    find_existing_ingest_duplicate,
    invoice_number_duplicate_exists,
)
from app.services.ingest.ingest_fanout_service import ingest_upload_file
from app.services.invoice.invoice_data import InvoiceData
from app.tenant_ids import TESTING_TENANT_UUID
from app.utils.hashing import compute_sha256_bytes


@pytest.fixture(autouse=True)
def _layer1_flags_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FUZZY_DUPLICATE_CHECK_ENABLED", "false")
    monkeypatch.setenv("CONTENT_SIMILARITY_CHECK_ENABLED", "false")
    monkeypatch.setenv("DUPLICATE_INVOICE_CHECK_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_layer1_file_hash_unique_constraint_on_model() -> None:
    from sqlalchemy import UniqueConstraint

    args = Invoice.__table_args__
    assert any(
        isinstance(item, UniqueConstraint) and item.name == "uq_invoice_tenant_hash"
        for item in args
    )
    assert "file_hash" in Invoice.__table__.c


def test_layer1_evaluate_processed_is_shadow() -> None:
    existing = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        file_hash="abc",
        currency="AUD",
    )
    decision = evaluate_file_hash_duplicate(existing)
    assert decision.action == "shadow_duplicate"


@pytest.mark.asyncio
async def test_layer1_identical_file_reupload_caught(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes = b"%PDF-1.4 layer1-exact-identical"
    file_hash = compute_sha256_bytes(pdf_bytes)

    original = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash=file_hash,
        vendor="Acme",
        invoice_no="INV-L1-1",
        total=Decimal("10.00"),
    )
    db_session.add(original)
    await db_session.flush()

    from app.services.extraction.pdf_page_text_service import PdfPageTextExtraction

    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.extract_pdf_page_texts",
        lambda _path: PdfPageTextExtraction(pages=[]),
    )
    monkeypatch.setattr(
        "app.services.ingest.ingest_fanout_service.store_invoice_pdf",
        lambda *args, **kwargs: "uploads/layer1.pdf",
    )

    result = await ingest_upload_file(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="hv-org",
        tenant_name="High Volt Analytics",
        filename="layer1.pdf",
        data=pdf_bytes,
        purchase_document_type=None,
    )
    await db_session.flush()

    assert result.duplicate_handled is True
    assert len(result.invoice_ids) == 1
    shadow = await db_session.get(Invoice, result.invoice_ids[0])
    assert shadow is not None
    assert shadow.status == InvoiceStatus.DUPLICATE_SKIPPED
    assert shadow.file_hash is None

    found = await find_existing_ingest_duplicate(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        file_hash=file_hash,
    )
    assert found is not None
    assert found.id == original.id


@pytest.mark.asyncio
async def test_layer1_exact_invoice_no_vendor_before_fuzzy(
    db_session: AsyncSession,
) -> None:
    """Exact invoice_no + vendor match without relying on fuzzy/content-similarity."""
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Acme Pty Ltd",
            invoice_no="INV-EXACT-9",
            status=InvoiceStatus.PROCESSED,
            currency="AUD",
            file_hash="other-bytes-hash",
            total=Decimal("50.00"),
        )
    )
    await db_session.flush()

    data = InvoiceData(
        vendor="Acme Pty Ltd",
        invoice_no="INV-EXACT-9",
        total=Decimal("999.00"),
        currency="AUD",
    )
    hit = await invoice_number_duplicate_exists(
        db_session,
        data,
        tenant_id=TESTING_TENANT_UUID,
    )
    assert hit is not None
    assert hit.invoice_no == "INV-EXACT-9"
