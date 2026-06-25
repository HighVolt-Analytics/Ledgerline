"""Tests for derive_current_stage — inbox pipeline label from audit + status."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.services.pipeline_stages import derive_current_stage
from tests.conftest import TESTING_TENANT_UUID


def _log(event: str, *, invoice_id: int = 1) -> AuditLog:
    return AuditLog(
        event=event,
        invoice_id=invoice_id,
        created_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        detail={},
    )


@pytest.mark.asyncio
async def test_current_stage_processed_before_post(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="processed-stage",
    )
    db_session.add(inv)
    await db_session.flush()

    logs = [
        _log("invoice_processed", invoice_id=inv.id),
    ]
    label, state = derive_current_stage(inv, logs)
    assert label == "Processed"
    assert state == "pending"


@pytest.mark.asyncio
async def test_current_stage_posted(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="posted-stage",
    )
    db_session.add(inv)
    await db_session.flush()

    processed = _log("invoice_processed", invoice_id=inv.id)
    published = _log("invoice_published_to_ledger", invoice_id=inv.id)
    db_session.add_all([processed, published])
    await db_session.flush()
    published.id = processed.id + 1

    label, state = derive_current_stage(inv, [processed, published])
    assert label == "Posted"
    assert state == "done"


@pytest.mark.asyncio
async def test_current_stage_exception_needs_review_maps_to_blocked_step(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="needs_review",
        currency="AUD",
        file_hash="exception-stage",
        validation_results='[{"rule":"VR01","passed":true,"message":"ok","skipped":false}]',
    )
    db_session.add(inv)
    await db_session.flush()

    logs = [
        _log("parse_completed", invoice_id=inv.id),
        _log("validation_passed", invoice_id=inv.id),
        _log("mapping_applied", invoice_id=inv.id),
    ]
    label, state = derive_current_stage(inv, logs)
    assert label == "Mapped"
    assert state == "pending"


@pytest.mark.asyncio
async def test_current_stage_duplicate_skipped(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.DUPLICATE_SKIPPED,
        currency="AUD",
        file_hash=None,
    )
    db_session.add(inv)
    await db_session.flush()

    label, state = derive_current_stage(
        inv,
        [_log("duplicate_skipped", invoice_id=inv.id)],
    )
    assert label == "Duplicate"
    assert state == "fail"


@pytest.mark.asyncio
async def test_current_stage_rejected(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.REJECTED,
        currency="AUD",
        file_hash="rejected-stage",
    )
    db_session.add(inv)
    await db_session.flush()

    label, state = derive_current_stage(
        inv,
        [_log("invoice_rejected", invoice_id=inv.id)],
    )
    assert label == "Rejected"
    assert state == "fail"
