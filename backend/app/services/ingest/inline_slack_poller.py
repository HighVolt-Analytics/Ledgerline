"""Background Slack DM polling when Events API is not delivering (local / sync mode)."""

from __future__ import annotations

import asyncio
import time

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_poll_task: asyncio.Task[None] | None = None
_poll_lock = asyncio.Lock()
_shutting_down = False
_STOP_TIMEOUT_SECONDS = 10.0


def _slack_polling_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.slack_client_id.strip()
        and settings.slack_client_secret.strip()
        and settings.slack_signing_secret.strip()
    )


async def _poll_once() -> None:
    if _shutting_down:
        return
    if _poll_lock.locked():
        logger.info("inline_slack_poll_skipped", reason="already_running")
        return

    async with _poll_lock:
        if _shutting_down:
            return
        from app.services.ingest.slack_poll_service import poll_all_connected_slack_accounts

        logger.info("inline_slack_poll_cycle_started")
        try:
            result = await poll_all_connected_slack_accounts()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("inline_slack_poll_failed", error=str(exc))
            return
        logger.info("inline_slack_poll_cycle_finished", **result)


async def _poll_loop() -> None:
    settings = get_settings()
    interval_seconds = max(30, int(settings.slack_poll_interval_seconds))

    # First poll soon after startup so local DMs are picked up quickly.
    try:
        await asyncio.sleep(8)
    except asyncio.CancelledError:
        raise

    while not _shutting_down:
        started = time.monotonic()
        try:
            await _poll_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("inline_slack_poll_loop_error", error=str(exc))
        if _shutting_down:
            break
        elapsed = time.monotonic() - started
        sleep_for = max(0.0, interval_seconds - elapsed)
        logger.info(
            "inline_slack_poll_sleep",
            elapsed_seconds=round(elapsed, 1),
            sleep_seconds=round(sleep_for, 1),
            interval_seconds=interval_seconds,
        )
        try:
            await asyncio.sleep(sleep_for)
        except asyncio.CancelledError:
            raise


def start_inline_slack_poller() -> asyncio.Task[None] | None:
    """Start periodic Slack DM polling for sync-processing deployments."""
    global _poll_task, _shutting_down

    settings = get_settings()
    if not settings.sync_processing:
        return None
    if not settings.slack_poll_enabled:
        logger.info("inline_slack_poller_skipped", reason="disabled")
        return None
    if not _slack_polling_configured():
        logger.info("inline_slack_poller_skipped", reason="slack_app_not_configured")
        return None
    if _poll_task is not None and not _poll_task.done():
        return _poll_task

    _shutting_down = False
    _poll_task = asyncio.create_task(_poll_loop(), name="inline-slack-poller")
    logger.info(
        "inline_slack_poller_started",
        interval_seconds=max(30, int(settings.slack_poll_interval_seconds)),
    )
    return _poll_task


async def stop_inline_slack_poller() -> None:
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
    logger.info("inline_slack_poller_stopped")
