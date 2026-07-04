"""Tests for post-ingest pipeline queueing."""

from unittest.mock import patch
from uuid import UUID

import pytest

from app.workers.tasks import queue_invoices_for_processing


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
