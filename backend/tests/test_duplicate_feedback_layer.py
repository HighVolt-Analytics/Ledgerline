"""Layer 7 — reviewer resolution feedback on approve/reject audits."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.services.approval.approval_service import (
    permanently_delete_invoice,
    reject_invoice,
    resolution_for_review_action,
)
from app.tenant_ids import TESTING_TENANT_UUID


def test_resolution_mapping() -> None:
    assert resolution_for_review_action(action="approve", previous_status="exception") == "not_duplicate"
    assert (
        resolution_for_review_action(action="reject", previous_status="exception")
        == "confirmed_duplicate"
    )
    assert (
        resolution_for_review_action(action="delete", previous_status="duplicate_skipped")
        == "confirmed_duplicate"
    )


@pytest.mark.asyncio
async def test_reject_audit_includes_resolution(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.approval.approval_service.repair_invoice_stored_path",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.approval.approval_service.is_rejected_storage_path",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        "app.services.approval.approval_service.clear_invoice_posting_artifacts",
        lambda *args, **kwargs: None,
    )

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        vendor="Acme",
        invoice_no="INV-L7-1",
        file_hash="l7-reject-hash",
        raw_file_path="rejected/already.pdf",
    )
    db_session.add(inv)
    await db_session.flush()

    await reject_invoice(db_session, inv)
    await db_session.flush()

    row = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.invoice_id == inv.id,
                AuditLog.event == "invoice_rejected",
            )
        )
    ).scalar_one()
    assert row.detail["resolution"] == "confirmed_duplicate"
    assert row.detail["previous_status"] == "exception"


@pytest.mark.asyncio
async def test_skip_logged_includes_original_invoice_id(
    db_session: AsyncSession,
) -> None:
    from app.services.dossier.document_duplicate_service import resolve_ingest_duplicate

    existing = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.DUPLICATE_SKIPPED,
        currency="AUD",
        file_hash=None,
        vendor="Acme",
    )
    db_session.add(existing)
    await db_session.flush()

    await resolve_ingest_duplicate(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        existing=existing,
        file_hash="ignored-hash",
        capture_source="upload",
        email_attachment_name="dup.pdf",
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.invoice_id == existing.id,
                AuditLog.event == "duplicate_skipped",
            )
        )
    ).scalars().all()
    assert row
    assert row[-1].detail.get("original_invoice_id") == existing.id
