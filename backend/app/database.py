"""Async SQLAlchemy engine and session."""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.tenant_context import get_request_tenant_id
from app.tenant_rls import apply_rls_session_context, clear_rls_session_context


class Base(DeclarativeBase):
    pass


def _build_engine() -> AsyncEngine:
    """Celery workers use NullPool to avoid stale asyncpg connections across asyncio.run()."""
    url = get_settings().database_url
    connect_args = {"command_timeout": 60, "timeout": 30}
    if os.getenv("CELERY_WORKER") == "1":
        return create_async_engine(url, poolclass=NullPool, connect_args=connect_args)
    return create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,
        connect_args=connect_args,
    )


engine = _build_engine()
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def dispose_engine() -> None:
    """Release pool connections after a Celery task finishes."""
    await engine.dispose()


async def _apply_rls_from_context(session: AsyncSession) -> None:
    await apply_rls_session_context(session, get_request_tenant_id())


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            await _apply_rls_from_context(session)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await clear_rls_session_context(session)


@asynccontextmanager
async def db_session_with_rls(tenant_id: int | None):
    async with async_session_factory() as session:
        try:
            await apply_rls_session_context(session, tenant_id)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await clear_rls_session_context(session)
