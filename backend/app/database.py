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
from app.utils.logger import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    pass


install_azure_dns_fallback()


def _build_engine() -> AsyncEngine:
    """Celery workers use NullPool to avoid stale asyncpg connections across asyncio.run()."""
    settings = get_settings()
    url = strip_ssl_query_params(settings.database_url)
    connect_args = asyncpg_connect_args(settings.database_url)
    if os.getenv("CELERY_WORKER") == "1":
        return create_async_engine(url, poolclass=NullPool, connect_args=connect_args)
    # Azure closes idle connections aggressively; recycle before the server does.
    # Also prefer recently-used sockets (LIFO) so mid-request idle drops are rarer.
    azure = "postgres.database.azure.com" in settings.database_url
    pool_recycle = 180 if azure else 900
    # Cap pool so staging+prod sharing one Flexible Server do not exhaust max_connections.
    pool_size = max(1, int(settings.db_pool_size))
    max_overflow = max(0, int(settings.db_max_overflow))
    if azure:
        pool_size = min(pool_size, 8)
        max_overflow = min(max_overflow, 8)
    pool_timeout = max(5, int(settings.db_pool_timeout_seconds))
    logger.info(
        "db_pool_configured",
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=pool_recycle,
        pool_timeout=pool_timeout,
        azure=azure,
    )
    return create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=pool_recycle,
        pool_timeout=pool_timeout,
        pool_use_lifo=True,
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


async def _safe_rollback(session: AsyncSession) -> None:
    try:
        await session.rollback()
    except Exception:
        logger.warning("db_rollback_failed", exc_info=True)
        try:
            await session.invalidate()
        except Exception:
            pass


async def _safe_clear_rls(session: AsyncSession) -> None:
    try:
        await clear_rls_session_context(session)
    except Exception:
        logger.warning("rls_clear_failed", exc_info=True)


async def _safe_clear_platform_lookup(session: AsyncSession) -> None:
    try:
        await clear_platform_lookup_session(session)
    except Exception:
        logger.warning("platform_lookup_clear_failed", exc_info=True)


async def _flush_xero_auto_push(session: AsyncSession) -> None:
    """Await Xero export after commit. Never fail the originating transaction."""
    try:
        from app.integrations.xero.auto_push import flush_scheduled_xero_auto_push

        await flush_scheduled_xero_auto_push(session)
    except Exception:
        logger.warning("xero_auto_push_flush_failed", exc_info=True)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await _safe_rollback(session)
            raise
        else:
            await _flush_xero_auto_push(session)
        finally:
            await _safe_clear_rls(session)


async def get_preauth_db() -> AsyncGenerator[AsyncSession, None]:
    """Session for login/OTP flows that must enumerate memberships across tenants."""
    async with async_session_factory() as session:
        try:
            await apply_platform_lookup_session(session)
            yield session
            await session.commit()
        except Exception:
            await _safe_rollback(session)
            raise
        finally:
            await _safe_clear_platform_lookup(session)


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
            await _safe_rollback(session)
            raise
        else:
            await _flush_xero_auto_push(session)
        finally:
            await _safe_clear_rls(session)


@asynccontextmanager
async def platform_lookup_session():
    """Short-lived session for cross-tenant routing lookups (webhooks, workers)."""
    async with async_session_factory() as session:
        try:
            await apply_platform_lookup_session(session)
            yield session
        finally:
            await _safe_clear_platform_lookup(session)
