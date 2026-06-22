"""Async SQLAlchemy engine and session."""

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.azure_env import asyncpg_connect_args, strip_ssl_query_params
from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _build_engine() -> AsyncEngine:
    """Celery workers use NullPool to avoid stale asyncpg connections across asyncio.run()."""
    url = strip_ssl_query_params(get_settings().database_url)
    connect_args = asyncpg_connect_args(get_settings().database_url)
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

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
