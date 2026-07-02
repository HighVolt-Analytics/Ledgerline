"""PostgreSQL RLS session context via set_config."""

import uuid


from app.tenant_context import set_rls_tenant_id


class RlsSessionContextError(RuntimeError):
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
    await apply_rls_session_context(session, None)

async def apply_platform_lookup_session(session) -> None:
    """Disable RLS for narrow cross-tenant routing (webhooks, worker id resolution)."""
    from sqlalchemy import text

    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    await session.execute(text("SET LOCAL row_security = off"))


async def clear_platform_lookup_session(session) -> None:
    from sqlalchemy import text

    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    await session.execute(text("SET LOCAL row_security = on"))
