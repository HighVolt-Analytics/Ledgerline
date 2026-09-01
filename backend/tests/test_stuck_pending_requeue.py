"""Stuck PENDING recovery after a lost pipeline enqueue."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.services.audit.audit_service import log_event
from app.services.invoice.stuck_pending_requeue_service import find_stuck_pending_invoice_ids
from app.tenant_ids import TESTING_TENANT_UUID
from app.workers.tasks import enqueue_invoice_pipelines, requeue_stuck_pending_for_tenant


@pytest.mark.asyncio
async def test_find_stuck_pending_skips_fresh_and_active(
    db_session: AsyncSession,
) -> None:
    fresh = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        raw_file_path="azureblob://invoices/fresh.png",
        file_hash="fresh-hash",
        currency="AUD",
    )
    stuck = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        raw_file_path="azureblob://invoices/stuck.png",
        file_hash="stuck-hash",
        currency="AUD",
    )
    no_file = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        raw_file_path=None,
        file_hash="nofile-hash",
        currency="AUD",
    )
    db_session.add_all([fresh, stuck, no_file])
    await db_session.flush()

    await log_event(db_session, "document_ingested", invoice_id=fresh.id, detail={})
    await log_event(db_session, "classification_resolved", invoice_id=stuck.id, detail={})
    await db_session.flush()

    stale_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    await db_session.execute(
        update(AuditLog)
        .where(AuditLog.invoice_id == stuck.id)
        .values(created_at=stale_at)
    )
    await db_session.flush()

    found = await find_stuck_pending_invoice_ids(
        db_session,
        TESTING_TENANT_UUID,
        stale_after_seconds=180,
        limit=25,
    )
    assert stuck.id in found
    assert fresh.id not in found
    assert no_file.id not in found

@pytest.mark.asyncio
async def test_requeue_stuck_pending_skips_already_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SYNC_PROCESSING", "true")
    get_settings.cache_clear()
    tenant_id = TESTING_TENANT_UUID

    class _FakeCtx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            return None

    async def fake_find(_session, _tid, *, stale_after_seconds, limit):
        return [99, 100]

    with (
        patch("app.workers.tasks.db_session_with_rls", return_value=_FakeCtx()),
        patch(
            "app.services.invoice.stuck_pending_requeue_service.find_stuck_pending_invoice_ids",
            side_effect=fake_find,
        ),
        patch(
            "app.workers.tasks.filter_not_already_queued",
            return_value=[100],
        ),
        patch(
            "app.workers.tasks.queue_invoices_for_processing",
            new_callable=AsyncMock,
        ) as mock_queue,
    ):
        ids = await requeue_stuck_pending_for_tenant(tenant_id)
        assert ids == [100]
        mock_queue.assert_awaited_once_with([100], tenant_id=tenant_id)

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_requeue_stuck_pending_enqueues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SYNC_PROCESSING", "true")
    get_settings.cache_clear()
    tenant_id = TESTING_TENANT_UUID

    class _FakeCtx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            return None

    async def fake_find(_session, _tid, *, stale_after_seconds, limit):
        assert stale_after_seconds == 60
        assert limit == 10
        return [99]

    with (
        patch("app.workers.tasks.db_session_with_rls", return_value=_FakeCtx()),
        patch(
            "app.services.invoice.stuck_pending_requeue_service.find_stuck_pending_invoice_ids",
            side_effect=fake_find,
        ),
        patch(
            "app.workers.tasks.queue_invoices_for_processing",
            new_callable=AsyncMock,
        ) as mock_queue,
    ):
        ids = await requeue_stuck_pending_for_tenant(
            tenant_id,
            stale_after_seconds=60,
            limit=10,
        )
        assert ids == [99]
        mock_queue.assert_awaited_once_with([99], tenant_id=tenant_id)

    get_settings.cache_clear()


def test_enqueue_logs_celery_task_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNC_PROCESSING", "false")
    get_settings.cache_clear()
    tenant_id = UUID("550e8400-e29b-41d4-a716-446655440000")
    result = MagicMock()
    result.id = "task-abc-123"
    with patch("app.workers.tasks.process_invoice_task.delay", return_value=result) as mock_delay, patch(
        "app.workers.tasks.try_claim_pipeline_enqueue", return_value=True
    ):
        status = enqueue_invoice_pipelines([9], tenant_id=tenant_id)
        assert status == "queued"
        mock_delay.assert_called_once_with(9, tenant_id=str(tenant_id))
    get_settings.cache_clear()
