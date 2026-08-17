"""RLS cleanup must not reconnect after commit/rollback."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.tenant_rls import clear_platform_lookup_session, clear_rls_session_context


class _FakeSession:
    def __init__(self, *, in_transaction: bool, dialect: str = "postgresql") -> None:
        self._in_transaction = in_transaction
        self.execute = AsyncMock(side_effect=TimeoutError("connect timed out"))
        self.invalidate = AsyncMock()
        self.get_bind = lambda: SimpleNamespace(dialect=SimpleNamespace(name=dialect))

    def in_transaction(self) -> bool:
        return self._in_transaction


@pytest.mark.asyncio
async def test_clear_rls_skips_sql_when_transaction_already_ended() -> None:
    session = _FakeSession(in_transaction=False)
    await clear_rls_session_context(session)
    session.execute.assert_not_awaited()
    session.invalidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_clear_rls_swallows_connection_errors_in_open_transaction() -> None:
    session = _FakeSession(in_transaction=True)
    await clear_rls_session_context(session)
    session.execute.assert_awaited()
    session.invalidate.assert_awaited()


@pytest.mark.asyncio
async def test_clear_platform_lookup_skips_sql_when_transaction_already_ended() -> None:
    session = _FakeSession(in_transaction=False)
    await clear_platform_lookup_session(session)
    session.execute.assert_not_awaited()
