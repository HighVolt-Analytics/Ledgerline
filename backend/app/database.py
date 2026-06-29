"""Async SQLAlchemy engine and session."""

import os
import uuid
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

from app.azure_env import asyncpg_connect_args, install_azure_dns_fallback, strip_ssl_query_params
from app.config import get_settings
from app.tenant_rls import (
    apply_platform_lookup_session,
    apply_rls_session_context,
    clear_platform_lookup_session,
    clear_rls_session_context,
)
from app.tenant_scoped import coerce_tenant_uuid


class Base(DeclarativeBase):
    pass


install_azure_dns_fallback()


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
        pool_size=10,
        max_overflow=20,
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
        finally:
            await clear_rls_session_context(session)


async def get_preauth_db() -> AsyncGenerator[AsyncSession, None]:
    """Session for login/OTP flows that must enumerate memberships across tenants."""
    async with async_session_factory() as session:
        try:
            await apply_platform_lookup_session(session)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await clear_platform_lookup_session(session)


@asynccontextmanager
async def db_session_with_rls(tenant_id: uuid.UUID | int | None):
    """Open a session with PostgreSQL RLS scoped to one tenant."""
    tid = coerce_tenant_uuid(tenant_id)
    async with async_session_factory() as session:
        try:
            await apply_rls_session_context(session, tid)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await clear_rls_session_context(session)


@asynccontextmanager
async def platform_lookup_session():
    """Short-lived session for cross-tenant routing lookups (webhooks, workers)."""
    async with async_session_factory() as session:
        try:
            await apply_platform_lookup_session(session)
            yield session
        finally:
            await clear_platform_lookup_session(session)
