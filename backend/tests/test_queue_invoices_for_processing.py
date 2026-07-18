"""Tests for post-ingest pipeline queueing."""

from unittest.mock import patch
from uuid import UUID

import pytest

from app.config import get_settings
from app.workers.tasks import enqueue_invoice_pipelines, queue_invoices_for_processing


@pytest.fixture(autouse=True)
def _sync_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNC_PROCESSING", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_queue_invoices_for_processing_single() -> None:
    tenant_id = UUID("550e8400-e29b-41d4-a716-446655440000")
    with patch("app.workers.tasks.asyncio.create_task") as mock_create_task:
        await queue_invoices_for_processing([42], tenant_id=tenant_id)
        mock_create_task.assert_called_once()
        assert mock_create_task.call_args.kwargs.get("name") == "invoice-pipeline-42"


@pytest.mark.asyncio
async def test_queue_invoices_for_processing_batch() -> None:
    tenant_id = UUID("550e8400-e29b-41d4-a716-446655440000")
    with patch("app.workers.tasks.asyncio.create_task") as mock_create_task:
        await queue_invoices_for_processing([1, 2, 1], tenant_id=tenant_id)
        mock_create_task.assert_called_once()
        assert mock_create_task.call_args.kwargs.get("name") == "invoice-pipeline-batch-1"


@pytest.mark.asyncio
async def test_queue_invoices_for_processing_noop_on_empty() -> None:
    tenant_id = UUID("550e8400-e29b-41d4-a716-446655440000")
    with patch("app.workers.tasks.asyncio.create_task") as mock_create_task:
        await queue_invoices_for_processing([], tenant_id=tenant_id)
        mock_create_task.assert_not_called()


def test_enqueue_prefers_celery_when_sync_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNC_PROCESSING", "false")
    get_settings.cache_clear()
    tenant_id = UUID("550e8400-e29b-41d4-a716-446655440000")
    with patch("app.workers.tasks.process_invoice_task.delay") as mock_delay:
        status = enqueue_invoice_pipelines([9], tenant_id=tenant_id)
        assert status == "queued"
        mock_delay.assert_called_once_with(9, tenant_id=str(tenant_id))
