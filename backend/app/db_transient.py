"""Detect and retry transient PostgreSQL/asyncpg connection failures."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.logger import get_logger

logger = get_logger(__name__)

_TRANSIENT_TYPE_NAMES = frozenset(
    {
        "ConnectionDoesNotExistError",
        "ConnectionResetError",
        "BrokenPipeError",
        "InterfaceError",
        "CannotConnectNowError",
        "ConnectionRefusedError",
        "TimeoutError",
        "OSError",
    }
)

T = TypeVar("T")


def is_transient_connection_error(exc: BaseException) -> bool:
    """True when the DB server or network dropped an in-flight connection."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if type(current).__name__ in _TRANSIENT_TYPE_NAMES:
            return True
        if isinstance(current, DBAPIError):
            if current.connection_invalidated:
                return True
            orig = getattr(current, "orig", None)
            if orig is not None and orig is not current:
                current = orig
                continue
        current = current.__cause__
    return False


async def run_with_transient_db_retry(
    session: AsyncSession,
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 2,
    before_retry: Callable[[], Awaitable[None]] | None = None,
) -> T:
    """Re-run once on a fresh pooled connection after invalidate()."""
    last_exc: BaseException | None = None
    for attempt in range(attempts):
        try:
            return await operation()
        except BaseException as exc:
            last_exc = exc
            if attempt + 1 >= attempts or not is_transient_connection_error(exc):
                raise
            logger.warning(
                "db_transient_retry",
                attempt=attempt + 1,
                error_type=type(exc).__name__,
                error=str(exc)[:240],
            )
            try:
                await session.rollback()
            except Exception:
                pass
            try:
                await session.invalidate()
            except Exception:
                pass
            if before_retry is not None:
                await before_retry()
    assert last_exc is not None
    raise last_exc
