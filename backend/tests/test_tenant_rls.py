"""Tenant RLS isolation tests."""



import pytest

from sqlalchemy import select, text

from sqlalchemy.ext.asyncio import AsyncSession



from app.models.invoice import Invoice, InvoiceStatus

from app.models.tenant import Tenant

from app.tenant_ids import TESTING_TENANT_UUID

from app.tenant_rls import apply_rls_session_context, clear_rls_session_context





@pytest.mark.asyncio

async def test_rls_context_survives_rollback(db_session: AsyncSession) -> None:

    if db_session.get_bind().dialect.name != "postgresql":

        pytest.skip("PostgreSQL RLS is not active on SQLite test database")



    await apply_rls_session_context(db_session, TESTING_TENANT_UUID)

    await db_session.rollback()

    await apply_rls_session_context(db_session, TESTING_TENANT_UUID)



    ctx = await db_session.execute(text("SELECT current_setting('app.tenant_id', true)"))

    assert ctx.scalar() == str(TESTING_TENANT_UUID)





@pytest.mark.asyncio

async def test_rls_hides_other_tenant_invoices(db_session: AsyncSession) -> None:

    if db_session.get_bind().dialect.name != "postgresql":

        pytest.skip("PostgreSQL RLS is not active on SQLite test database")



    import uuid



    other_tid = uuid.uuid4()

    db_session.add(Tenant(id=other_tid, name="Other", slug="other-rls-test"))

    db_session.add(Invoice(tenant_id=other_tid, status=InvoiceStatus.PENDING, currency="AUD"))

    await db_session.flush()



    await apply_rls_session_context(db_session, TESTING_TENANT_UUID)

    rows = (

        await db_session.execute(select(Invoice).where(Invoice.tenant_id == other_tid))

    ).scalars().all()

    assert rows == []



    await clear_rls_session_context(db_session)

    ctx = await db_session.execute(text("SELECT current_setting('app.tenant_id', true)"))

    assert ctx.scalar() in ("", None)

