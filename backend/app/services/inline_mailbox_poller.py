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
_shutting_down = False
_STOP_TIMEOUT_SECONDS = 10.0


async def _poll_once() -> None:
    if _shutting_down:
        return
    if _poll_lock.locked():
        logger.info("inline_mailbox_poll_skipped", reason="already_running")
        return

    async with _poll_lock:
        if _shutting_down:
            return
        from app.database import async_session_factory
        from app.services.tenant_context_service import list_active_tenant_ids

        async with async_session_factory() as session:
            try:
                tenant_ids = await list_active_tenant_ids(session)
            except asyncio.CancelledError:
                await session.rollback()
                raise
            except Exception:
                await session.rollback()
                raise

        for tid in tenant_ids:
            if _shutting_down:
                return
            try:
                result = await run_pipeline(tenant_id=tid, poll_inbox=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "inline_mailbox_poll_tenant_failed",
                    tenant_id=tid,
                    error=str(exc),
                )
                continue
            logger.info("inline_mailbox_poll_done", tenant_id=tid, **result)


async def _poll_loop() -> None:
    settings = get_settings()
    interval_seconds = max(60, settings.graph_poll_interval_minutes * 60)

    # First poll shortly after startup so local dev does not wait a full interval.
    try:
        await asyncio.sleep(15)
    except asyncio.CancelledError:
        raise

    while not _shutting_down:
        try:
            await _poll_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("inline_mailbox_poll_failed", error=str(exc))
        if _shutting_down:
            break
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            raise


def start_inline_mailbox_poller() -> asyncio.Task[None] | None:
    """Start periodic Graph inbox polling for local / sync-processing deployments."""
    global _poll_task, _shutting_down

    settings = get_settings()
    if not settings.sync_processing:
        return None
    if not is_graph_enabled():
        logger.info("inline_mailbox_poller_skipped", reason="graph_not_configured")
        return None
    if _poll_task is not None and not _poll_task.done():
        return _poll_task

    _shutting_down = False
    _poll_task = asyncio.create_task(_poll_loop(), name="inline-mailbox-poller")
    logger.info(
        "inline_mailbox_poller_started",
        interval_minutes=settings.graph_poll_interval_minutes,
    )
    return _poll_task


async def stop_inline_mailbox_poller() -> None:
    global _poll_task, _shutting_down
    if _poll_task is None:
        return

    _shutting_down = True
    task = _poll_task
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=_STOP_TIMEOUT_SECONDS)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    finally:
        _poll_task = None
        _shutting_down = False
    logger.info("inline_mailbox_poller_stopped")
