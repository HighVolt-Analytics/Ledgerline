
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""File-hash and VR02 duplicate detection."""

import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.rule_book_mapper import clear_classification_config_cache
from app.models.invoice import Invoice, InvoiceStatus
from app.services.document_duplicate_service import evaluate_file_hash_duplicate
from app.services.email_ingestion import EmailAttachment, RawEmail
from app.services.invoice_data import InvoiceData
from app.services.pipeline import ingest_email_attachments
from app.services.validator import vr02_unique


@pytest.fixture
def clean_org_rule_book(tmp_path, monkeypatch: pytest.MonkeyPatch):
    upload = tmp_path / "uploads"
    rule_books = upload / "rule_books"
    rule_books.mkdir(parents=True)
    template = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rule_book_demo.json"
    shutil.copy2(template, rule_books / "1_config.json")
    monkeypatch.setenv("UPLOAD_DIR", str(upload))
    monkeypatch.setenv("RULE_BOOK_CONFIG_PATH", str(template))
    get_settings.cache_clear()
    clear_classification_config_cache()
    yield
    get_settings.cache_clear()
    clear_classification_config_cache()


@pytest.fixture(autouse=True)
def _clear_config_cache() -> None:
    clear_classification_config_cache()
    yield
    clear_classification_config_cache()


def _matching_capture_email(data: bytes, *, message_id: str = "msg-dup") -> RawEmail:
    """Matches ec-1 in tests/fixtures/rule_book_demo.json."""

    return RawEmail(
        message_id=message_id,
        subject="Your AWS invoice for May 2026",
        sender="billing@amazon.com",
        mailbox_email="accounts@acme-hospitality.com.au",
        attachments=[
            EmailAttachment(
                filename="AWS-Invoice-May.pdf",
                content_type="application/pdf",
                data=data,
            )
        ],
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (InvoiceStatus.PENDING, "skip_in_progress"),
        (InvoiceStatus.PROCESSED, "shadow_duplicate"),
        (InvoiceStatus.REJECTED, "reingest_rejected"),
        (InvoiceStatus.DUPLICATE_SKIPPED, "skip_logged"),
    ],
)
def test_evaluate_file_hash_duplicate(status: InvoiceStatus, expected: str) -> None:
    existing = Invoice(tenant_id=TESTING_TENANT_UUID, status=status, file_hash="abc", currency="AUD")
    decision = evaluate_file_hash_duplicate(existing)
    assert decision.action == expected
    assert decision.existing is existing


@pytest.mark.asyncio
async def test_email_duplicate_preserves_processed_invoice(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    clean_org_rule_book,
) -> None:
    pdf_bytes = b"%PDF-1.4 duplicate-test"
    file_hash = "will-be-overwritten"

    from app.utils.hashing import compute_sha256_bytes

    file_hash = compute_sha256_bytes(pdf_bytes)

    processed = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Vendor Co",
        invoice_no="INV-100",
        status=InvoiceStatus.PROCESSED,
        file_hash=file_hash,
        currency="AUD",
        total=Decimal("100.00"),
    )
    db_session.add(processed)
    await db_session.flush()

    monkeypatch.setattr(
        "app.services.pipeline._finish_email_message",
        lambda *args, **kwargs: None,
    )

    result = await ingest_email_attachments(
        db_session,
        [_matching_capture_email(pdf_bytes)],
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="hv-org",
    )
    assert result.ingested_count == 0

    await db_session.refresh(processed)
    assert processed.status == InvoiceStatus.PROCESSED

    rows = (await db_session.execute(select(Invoice))).scalars().all()
    assert len(rows) == 2
    shadow = next(r for r in rows if r.id != processed.id)
    assert shadow.status == InvoiceStatus.DUPLICATE_SKIPPED
    assert shadow.file_hash is None


@pytest.mark.asyncio
async def test_email_duplicate_in_progress_logs_without_second_row(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    clean_org_rule_book,
) -> None:
    from app.utils.hashing import compute_sha256_bytes

    pdf_bytes = b"%PDF-1.4 in-flight-dup"
    file_hash = compute_sha256_bytes(pdf_bytes)

    pending = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PARSING,
        file_hash=file_hash,
        currency="AUD",
    )
    db_session.add(pending)
    await db_session.flush()

    monkeypatch.setattr(
        "app.services.pipeline._finish_email_message",
        lambda *args, **kwargs: None,
    )

    result = await ingest_email_attachments(
        db_session,
        [_matching_capture_email(pdf_bytes, message_id="msg-2")],
        tenant_id=TESTING_TENANT_UUID,
        tenant_slug="hv-org",
    )
    assert result.ingested_count == 0
    rows = (await db_session.execute(select(Invoice))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == InvoiceStatus.PARSING


@pytest.mark.asyncio
async def test_vr02_ignores_rejected_invoice(
    db_session: AsyncSession,
    sample_invoice_data: InvoiceData,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DUPLICATE_INVOICE_CHECK_ENABLED", "true")
    get_settings.cache_clear()

    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Acme Pty Ltd",
            invoice_no="INV-DUP",
            status=InvoiceStatus.REJECTED,
            currency="AUD",
            file_hash="rejected-hash",
        )
    )
    await db_session.flush()

    sample_invoice_data.invoice_no = "INV-DUP"
    sample_invoice_data.vendor = "Acme Pty Ltd"
    result = await vr02_unique(sample_invoice_data, db_session, tenant_id=TESTING_TENANT_UUID)
    assert result.passed

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_pipeline_stages_show_duplicate_skipped(
    db_session: AsyncSession,
) -> None:
    from datetime import datetime, timezone

    from app.models.audit import AuditLog
    from app.services.pipeline_stages import build_pipeline_stages

    shadow = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        invoice_no="INV-1",
        status=InvoiceStatus.DUPLICATE_SKIPPED,
        currency="AUD",
        file_hash=None,
    )
    db_session.add(shadow)
    await db_session.flush()
    dup_log = AuditLog(
        event="duplicate_skipped",
        invoice_id=shadow.id,
        detail={
            "original_invoice_id": 99,
            "filename": "invoice.pdf",
            "source": "email",
        },
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(dup_log)
    await db_session.flush()

    steps = build_pipeline_stages(shadow, [dup_log])
    assert len(steps) == 2
    assert steps[1].stage == "Duplicate skipped"
    assert "Duplicate file skipped" in steps[1].detail
    assert "99" in steps[1].detail
