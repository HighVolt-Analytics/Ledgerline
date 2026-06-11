"""Background mailbox polling when SYNC_PROCESSING runs inside uvicorn (no Celery beat)."""

from __future__ import annotations

import asyncio

from app.config import get_settings
from app.services.graph_client import is_graph_enabled
from app.utils.logger import get_logger
from app.workers.tasks import run_pipeline

logger = get_logger(__name__)

_poll_task: asyncio.Task[None] | None = None
_poll_lock = asyncio.Lock()


async def _poll_once() -> None:
    if _poll_lock.locked():
        logger.info("inline_mailbox_poll_skipped", reason="already_running")
        return

    async with _poll_lock:
        result = await run_pipeline(poll_inbox=True)
        logger.info("inline_mailbox_poll_done", **result)


async def _poll_loop() -> None:
    settings = get_settings()
    interval_seconds = max(60, settings.graph_poll_interval_minutes * 60)

    # First poll shortly after startup so local dev does not wait a full interval.
    await asyncio.sleep(15)
    while True:
        try:
            await _poll_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("inline_mailbox_poll_failed", error=str(exc))
        await asyncio.sleep(interval_seconds)


def start_inline_mailbox_poller() -> asyncio.Task[None] | None:
    """Start periodic Graph inbox polling for local / sync-processing deployments."""
    global _poll_task

    settings = get_settings()
    if not settings.sync_processing:
        return None
    if not is_graph_enabled():
        logger.info("inline_mailbox_poller_skipped", reason="graph_not_configured")
        return None
    if _poll_task is not None and not _poll_task.done():
        return _poll_task

    _poll_task = asyncio.create_task(_poll_loop(), name="inline-mailbox-poller")
    logger.info(
        "inline_mailbox_poller_started",
        interval_minutes=settings.graph_poll_interval_minutes,
    )
    return _poll_task


async def stop_inline_mailbox_poller() -> None:
    global _poll_task
    if _poll_task is None:
        return
    _poll_task.cancel()
    try:
        await _poll_task
    except asyncio.CancelledError:
        pass
    _poll_task = None
    logger.info("inline_mailbox_poller_stopped")
