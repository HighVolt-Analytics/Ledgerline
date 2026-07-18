"""Process-wide throttle + scoped 429 circuit breakers for Azure chat / Foundry vision.

Concurrency gate is shared (one process-wide budget). Circuits are scoped so a vision
429 does not block segment LLM (and vice versa).
"""

from __future__ import annotations

import asyncio
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Literal

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

CircuitScope = Literal["chat", "vision"]

_gate_lock = threading.Lock()
_gate: threading.Semaphore | None = None
_gate_limit: int | None = None
_last_request_monotonic = 0.0
_pace_lock = threading.Lock()

_circuit_lock = threading.Lock()
_circuit_open_until_monotonic: dict[str, float] = {"chat": 0.0, "vision": 0.0}


def _configured_limit() -> int:
    return max(1, int(get_settings().azure_openai_max_concurrent))


def _min_interval_seconds() -> float:
    return max(0.0, float(get_settings().azure_openai_min_interval_seconds))


def _cooldown_floor_seconds() -> float:
    return max(15.0, float(get_settings().azure_openai_cooldown_seconds))


def _get_gate() -> threading.Semaphore:
    global _gate, _gate_limit
    limit = _configured_limit()
    with _gate_lock:
        if _gate is None or _gate_limit != limit:
            _gate = threading.Semaphore(limit)
            _gate_limit = limit
            logger.info("azure_openai_throttle_ready", max_concurrent=limit)
        return _gate


def azure_openai_cooling_down(scope: CircuitScope = "chat") -> bool:
    """True while the scoped 429 circuit is open."""
    with _circuit_lock:
        return time.monotonic() < _circuit_open_until_monotonic.get(scope, 0.0)


def azure_openai_cooldown_remaining_seconds(scope: CircuitScope = "chat") -> float:
    with _circuit_lock:
        return max(0.0, _circuit_open_until_monotonic.get(scope, 0.0) - time.monotonic())


def note_azure_openai_rate_limited(
    retry_after_seconds: float | None = None,
    *,
    scope: CircuitScope = "chat",
) -> None:
    """Open the scoped circuit after a 429 so same-scope callers fail fast."""
    wait = max(_cooldown_floor_seconds(), float(retry_after_seconds or 0.0))
    with _circuit_lock:
        until = time.monotonic() + wait
        if until > _circuit_open_until_monotonic.get(scope, 0.0):
            _circuit_open_until_monotonic[scope] = until
    logger.warning(
        "azure_openai_circuit_open",
        scope=scope,
        cooldown_seconds=round(wait, 1),
        remaining_seconds=round(azure_openai_cooldown_remaining_seconds(scope), 1),
    )


def note_azure_openai_success(*, scope: CircuitScope = "chat") -> None:
    """Clear the scoped circuit after a successful call."""
    with _circuit_lock:
        _circuit_open_until_monotonic[scope] = 0.0


def _pace_requests() -> None:
    """Enforce a small gap between calls so bursty retries don't re-trip 429."""
    global _last_request_monotonic
    gap = _min_interval_seconds()
    if gap <= 0:
        return
    with _pace_lock:
        now = time.monotonic()
        wait = (_last_request_monotonic + gap) - now
        if wait > 0:
            time.sleep(wait)
        _last_request_monotonic = time.monotonic()


async def _pace_requests_async() -> None:
    global _last_request_monotonic
    gap = _min_interval_seconds()
    if gap <= 0:
        return
    with _pace_lock:
        now = time.monotonic()
        wait = (_last_request_monotonic + gap) - now
    if wait > 0:
        await asyncio.sleep(wait)
    with _pace_lock:
        _last_request_monotonic = time.monotonic()


@contextmanager
def azure_openai_slot():
    """Sync slot for httpx Client chat/completions (segment LLM, etc.)."""
    gate = _get_gate()
    gate.acquire()
    try:
        _pace_requests()
        yield
    finally:
        gate.release()


@asynccontextmanager
async def azure_openai_slot_async():
    """Async slot — shares the same concurrency gate as sync callers."""
    gate = _get_gate()
    await asyncio.to_thread(gate.acquire)
    try:
        await _pace_requests_async()
        yield
    finally:
        gate.release()
