"""PostgreSQL RLS session context via set_config."""


class RlsSessionContextError(RuntimeError):
    pass


async def apply_rls_session_context(session, tenant_id: int | None) -> None:
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
    else:
        await session.execute(text("SELECT set_config('app.tenant_id', '', true)"))


async def clear_rls_session_context(session) -> None:
    await apply_rls_session_context(session, None)
