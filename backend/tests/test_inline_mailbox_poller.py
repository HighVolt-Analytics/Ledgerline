"""Inline mailbox poller (sync-processing local dev)."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.ingest.inline_mailbox_poller import (
    _poll_once,
    start_inline_mailbox_poller,
)
from app.workers import tasks as worker_tasks


def test_start_skipped_when_sync_processing_disabled() -> None:
    with patch("app.services.ingest.inline_mailbox_poller.get_settings") as mock_settings:
        mock_settings.return_value.sync_processing = False
        assert start_inline_mailbox_poller() is None


def test_start_skipped_when_no_mailbox_provider_configured() -> None:
    with (
        patch("app.services.ingest.inline_mailbox_poller.get_settings") as mock_settings,
        patch("app.services.ingest.inline_mailbox_poller.is_graph_enabled", return_value=False),
        patch(
            "app.services.ingest.inline_mailbox_poller.gmail_oauth_configured",
            return_value=False,
        ),
    ):
        mock_settings.return_value.sync_processing = True
        assert start_inline_mailbox_poller() is None


def test_start_allowed_when_only_gmail_configured() -> None:
    with (
        patch("app.services.ingest.inline_mailbox_poller.get_settings") as mock_settings,
        patch("app.services.ingest.inline_mailbox_poller.is_graph_enabled", return_value=False),
        patch(
            "app.services.ingest.inline_mailbox_poller.gmail_oauth_configured",
            return_value=True,
        ),
        patch("app.services.ingest.inline_mailbox_poller.asyncio.create_task") as mock_create,
    ):
        mock_settings.return_value.sync_processing = True
        mock_settings.return_value.graph_poll_interval_minutes = 2
        mock_settings.return_value.mailbox_poll_concurrency = 3
        mock_create.return_value = object()
        assert start_inline_mailbox_poller() is not None
        mock_create.assert_called_once()


def test_pipeline_active_is_scoped_per_tenant() -> None:
    tid_a = uuid4()
    tid_b = uuid4()
    worker_tasks._inline_active_tenants.clear()
    worker_tasks._inline_active_unscoped = 0

    assert not worker_tasks.is_inline_pipeline_active()
    assert not worker_tasks.is_inline_pipeline_active(tenant_id=tid_a)

    worker_tasks._mark_pipeline_enter(tid_a)
    try:
        assert worker_tasks.is_inline_pipeline_active()
        assert worker_tasks.is_inline_pipeline_active(tenant_id=tid_a)
        assert not worker_tasks.is_inline_pipeline_active(tenant_id=tid_b)
    finally:
        worker_tasks._mark_pipeline_exit(tid_a)

    assert not worker_tasks.is_inline_pipeline_active()


@pytest.mark.asyncio
async def test_poll_once_skips_pending_check_and_runs_concurrently() -> None:
    tid_a = uuid4()
    tid_b = uuid4()
    calls: list[dict] = []

    async def _fake_pipeline(**kwargs):
        calls.append(kwargs)
        return {"ingested": 0, "processed": 0}

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def rollback(self):
            return None

    with (
        patch(
            "app.services.tenant.tenant_context_service.list_active_tenant_ids_with_mailboxes",
            new=AsyncMock(return_value=[tid_a, tid_b]),
        ),
        patch(
            "app.database.async_session_factory",
            return_value=_FakeSession(),
        ),
        patch(
            "app.services.ingest.inline_mailbox_poller.run_pipeline",
            new=AsyncMock(side_effect=_fake_pipeline),
        ),
        patch("app.services.ingest.inline_mailbox_poller.get_settings") as mock_settings,
    ):
        mock_settings.return_value.mailbox_poll_concurrency = 2
        await _poll_once()

    assert len(calls) == 2
    assert {c["tenant_id"] for c in calls} == {tid_a, tid_b}
    assert all(c["poll_inbox"] is True for c in calls)
    assert all(c["skip_pending_check"] is True for c in calls)


@pytest.mark.asyncio
async def test_poll_once_does_not_skip_when_other_tenant_pipeline_active() -> None:
    """Global pipeline activity must not block mailbox polling."""
    tid = uuid4()
    other = uuid4()
    worker_tasks._inline_active_tenants.clear()
    worker_tasks._mark_pipeline_enter(other)
    try:
        with (
            patch(
                "app.services.tenant.tenant_context_service.list_active_tenant_ids_with_mailboxes",
                new=AsyncMock(return_value=[tid]),
            ),
            patch(
                "app.database.async_session_factory",
                return_value=_session_stub(),
            ),
            patch(
                "app.services.ingest.inline_mailbox_poller.run_pipeline",
                new=AsyncMock(return_value={"ingested": 0, "processed": 0}),
            ) as mock_run,
            patch("app.services.ingest.inline_mailbox_poller.get_settings") as mock_settings,
        ):
            mock_settings.return_value.mailbox_poll_concurrency = 1
            await _poll_once()
            mock_run.assert_awaited_once()
    finally:
        worker_tasks._mark_pipeline_exit(other)


def _session_stub():
    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def rollback(self):
            return None

    return _FakeSession()
