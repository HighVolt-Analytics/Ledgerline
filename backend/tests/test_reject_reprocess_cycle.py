"""Reject → reprocess cycle: publish invalidation, gate bypass, overrides."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry
from app.services.approval.approval_service import reject_invoice
from app.services.audit.audit_service import log_event
from app.services.classification.document_type_approval_service import has_document_approval
from app.services.dossier.document_duplicate_service import resolve_ingest_duplicate
from app.services.integration.publish_service import (
    is_published_from_audit_logs,
    is_published_to_ledger,
    publish_invoice_to_ledger,
)
from app.services.invoice.invoice_edit_service import invoice_has_manual_field_edits
from app.services.invoice.invoice_reset import requeue_invoice_for_pipeline
from app.services.invoice.processing_cycle_service import latest_cycle_reset_log_id_from_logs
from app.tenant_ids import TESTING_TENANT_UUID

_TID = TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_reject_invalidates_published_flag(
    db_session: AsyncSession,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()

    inv = Invoice(
        tenant_id=_TID,
        vendor="Acme",
        invoice_no="REJ-PUB-1",
        invoice_date=date(2026, 6, 1),
        total=Decimal("50.00"),
        status=InvoiceStatus.PROCESSED,
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        JournalEntry(
            invoice_id=inv.id,
            date=date(2026, 6, 1),
            account_code="6100",
            account_name="Office Expenses",
            debit=Decimal("50.00"),
            credit=Decimal("0"),
            entry_type=EntryType.DEBIT,
        )
    )
    await db_session.flush()

    await log_event(
        db_session,
        "invoice_processed",
        invoice_id=inv.id,
        detail={"status": "processed"},
    )
    assert await publish_invoice_to_ledger(db_session, inv) is True
    await db_session.flush()
    assert await is_published_to_ledger(db_session, inv.id) is True

    await reject_invoice(db_session, inv)
    await db_session.flush()

    assert await is_published_to_ledger(db_session, inv.id) is False


def test_is_published_from_audit_logs_respects_cycle_reset() -> None:
    from app.models.audit import AuditLog

    logs = [
        AuditLog(id=10, event="invoice_processed", invoice_id=1),
        AuditLog(id=20, event="invoice_published_to_ledger", invoice_id=1),
        AuditLog(id=30, event="invoice_rejected", invoice_id=1),
    ]
    assert is_published_from_audit_logs(logs) is False
    assert latest_cycle_reset_log_id_from_logs(logs) == 30


@pytest.mark.asyncio
async def test_prior_approval_does_not_bypass_after_reject(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=_TID,
        status=InvoiceStatus.REJECTED,
        currency="AUD",
        file_hash="cycle-approve-1",
        vendor="Acme",
        total=Decimal("100"),
        due_date=date(2026, 8, 1),
    )
    db_session.add(inv)
    await db_session.flush()

    await log_event(db_session, "invoice_approved", invoice_id=inv.id, detail={})
    await log_event(db_session, "invoice_rejected", invoice_id=inv.id, detail={})
    await db_session.flush()

    assert await has_document_approval(db_session, inv.id) is False


@pytest.mark.asyncio
async def test_approval_after_reject_enables_bypass(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=_TID,
        status=InvoiceStatus.PENDING,
        currency="AUD",
        file_hash="cycle-approve-2",
        vendor="Acme",
        total=Decimal("100"),
        due_date=date(2026, 8, 1),
    )
    db_session.add(inv)
    await db_session.flush()

    await log_event(db_session, "invoice_approved", invoice_id=inv.id, detail={})
    await log_event(db_session, "invoice_rejected", invoice_id=inv.id, detail={})
    await log_event(db_session, "invoice_approved", invoice_id=inv.id, detail={})
    await db_session.flush()

    assert await has_document_approval(db_session, inv.id) is True


@pytest.mark.asyncio
async def test_prior_manual_edits_ignored_after_requeue(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=_TID,
        status=InvoiceStatus.REJECTED,
        currency="AUD",
        file_hash="cycle-edits-1",
    )
    db_session.add(inv)
    await db_session.flush()

    await log_event(db_session, "invoice_fields_updated", invoice_id=inv.id, detail={})
    await log_event(db_session, "invoice_requeued", invoice_id=inv.id, detail={})
    await db_session.flush()

    assert await invoice_has_manual_field_edits(
        db_session,
        inv.id,
        tenant_id=_TID,
    ) is False


@pytest.mark.asyncio
async def test_full_requeue_clears_processing_overrides(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=_TID,
        status=InvoiceStatus.REJECTED,
        currency="AUD",
        file_hash="override-clear-1",
        processing_overrides={"skip_steps": ["validation", "playbook"]},
    )
    db_session.add(inv)
    await db_session.flush()

    await requeue_invoice_for_pipeline(db_session, inv, preserve_extracted_fields=False)
    await db_session.flush()

    assert inv.processing_overrides is None
    assert inv.status == InvoiceStatus.PENDING


@pytest.mark.asyncio
async def test_reingest_rejected_resolves_without_import_error(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    rejected_path = (
        upload_dir
        / f"tenants/{_TID}"
        / "rejected"
        / "Unrouted"
        / "Co"
        / "2026"
        / "May"
    )
    rejected_path.mkdir(parents=True)
    pdf = rejected_path / "INV-010_2026-05-04_id10.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    existing = Invoice(
        tenant_id=_TID,
        vendor="Co",
        invoice_no="INV-010",
        invoice_date=date(2026, 5, 4),
        status=InvoiceStatus.REJECTED,
        currency="AUD",
        file_hash="reingest-hash-1",
        storage_vendor_slug="co",
        raw_file_path=str(pdf),
        total=Decimal("50"),
    )
    db_session.add(existing)
    await db_session.flush()

    outcome = await resolve_ingest_duplicate(
        db_session,
        tenant_id=_TID,
        existing=existing,
        file_hash="reingest-hash-1",
        capture_source="email",
        email_sender="a@b.com",
        email_attachment_name="scan.pdf",
    )

    assert outcome.handled is True
    assert outcome.action == "reingest_rejected"
    assert existing.status == InvoiceStatus.PENDING
    assert existing.processing_overrides is None
    assert "invoice" in (existing.raw_file_path or "").replace("\\", "/")


@pytest.mark.asyncio
async def test_reprocess_from_rejected_restores_vault_and_queues_pending(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    rejected_path = (
        upload_dir / f"tenants/{_TID}" / "rejected" / "Unrouted" / "Co" / "2026" / "May"
    )
    rejected_path.mkdir(parents=True)
    pdf = rejected_path / "INV-011_2026-05-04_id11.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=_TID,
        vendor="Co",
        invoice_no="INV-011",
        invoice_date=date(2026, 5, 4),
        status=InvoiceStatus.REJECTED,
        currency="AUD",
        file_hash="reproc-api-1",
        storage_vendor_slug="co",
        raw_file_path=str(pdf),
        total=Decimal("50"),
        processing_overrides={"skip_steps": ["validation"]},
    )
    db_session.add(inv)
    await db_session.flush()

    await log_event(db_session, "invoice_published_to_ledger", invoice_id=inv.id, detail={})
    await log_event(db_session, "invoice_processed", invoice_id=inv.id, detail={})
    await db_session.flush()

    res = await client.post(f"/api/invoices/{inv.id}/reprocess")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["status"] == "pending"
    assert not body.get("processing_overrides", {}).get("skip_steps")
    assert body["published_to_ledger"] is False
    assert "invoice" in body["raw_file_path"].replace("\\", "/")
    assert not pdf.is_file()
