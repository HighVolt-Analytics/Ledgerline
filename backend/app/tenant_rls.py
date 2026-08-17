"""PostgreSQL RLS session context via set_config."""

import uuid

from app.tenant_context import set_rls_tenant_id
from app.utils.logger import get_logger

logger = get_logger(__name__)


class RlsSessionContextError(RuntimeError):
    pass


def _in_open_transaction(session) -> bool:
    try:
        return bool(session.in_transaction())
    except Exception:
        return False


async def _invalidate_session(session) -> None:
    try:
        await session.invalidate()
    except Exception:
        pass


async def apply_rls_session_context(session, tenant_id: uuid.UUID | None) -> None:
    """Set transaction-local app.tenant_id for RLS policies (Postgres only)."""
    from sqlalchemy import text

    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return

    if tenant_id is not None:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        set_rls_tenant_id(tenant_id)
    else:
        await session.execute(text("SELECT set_config('app.tenant_id', '', true)"))
        set_rls_tenant_id(None)


async def clear_rls_session_context(session) -> None:
    """Drop tenant GUC without opening a new connection after commit/rollback.

    ``set_config(..., is_local=true)`` already resets at transaction end. Opening
    a fresh connection just to clear it turns Azure drops into request 500s.
    """
    set_rls_tenant_id(None)
    try:
        if not _in_open_transaction(session):
            return
        await apply_rls_session_context(session, None)
    except Exception:
        logger.warning("rls_clear_failed", exc_info=True)
        await _invalidate_session(session)


async def apply_platform_lookup_session(session) -> None:
    """Disable RLS for narrow cross-tenant routing (webhooks, worker id resolution)."""
    from sqlalchemy import text

    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    await session.execute(text("SET LOCAL row_security = off"))


async def clear_platform_lookup_session(session) -> None:
    """Revert platform lookup GUC; never reconnect after the transaction ended."""
    from sqlalchemy import text

    try:
        bind = session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        if not _in_open_transaction(session):
            return
        await session.execute(text("SET LOCAL row_security = on"))
    except Exception:
        logger.warning("platform_lookup_clear_failed", exc_info=True)
        await _invalidate_session(session)
