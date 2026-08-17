"""Database session lifecycle — ensure flushed writes are committed."""

import pytest
from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.database import get_db


class _Base(DeclarativeBase):
    pass


class _FlushProbe(_Base):
    __tablename__ = "flush_probe"
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(32))


@pytest.mark.asyncio
async def test_get_db_commits_after_flush_only_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Services flush() before returning; commit must not depend on session.dirty."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)

    monkeypatch.setattr("app.database.async_session_factory", factory)

    async for session in get_db():
        session.add(_FlushProbe(id=1, label="committed"))
        await session.flush()
        assert not session.new and not session.dirty and not session.deleted

    async with factory() as verify:
        row = (await verify.execute(select(_FlushProbe).where(_FlushProbe.id == 1))).scalar_one_or_none()
        assert row is not None
        assert row.label == "committed"

    await engine.dispose()


@pytest.mark.asyncio
async def test_get_db_cleanup_does_not_raise_when_rls_clear_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Azure drops during RLS cleanup must not turn a finished request into 500."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)

    monkeypatch.setattr("app.database.async_session_factory", factory)

    async def boom(_session) -> None:
        raise TimeoutError("azure closed the socket")

    monkeypatch.setattr("app.database.clear_rls_session_context", boom)

    async for session in get_db():
        session.add(_FlushProbe(id=2, label="after-clear-fail"))
        await session.flush()

    async with factory() as verify:
        row = (
            await verify.execute(select(_FlushProbe).where(_FlushProbe.id == 2))
        ).scalar_one_or_none()
        assert row is not None
        assert row.label == "after-clear-fail"

    await engine.dispose()
