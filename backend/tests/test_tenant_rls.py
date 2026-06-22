"""Tenant RLS isolation tests."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.tenant_rls import apply_rls_session_context, clear_rls_session_context


@pytest.mark.asyncio
async def test_rls_hides_other_tenant_invoices(db_session: AsyncSession) -> None:
    db_session.add(Tenant(id=99, name="Other", slug="other-rls-test"))
    db_session.add(Invoice(tenant_id=99, status=InvoiceStatus.PENDING, currency="AUD"))
    await db_session.flush()

    await apply_rls_session_context(db_session, 1)
    rows = (await db_session.execute(select(Invoice).where(Invoice.tenant_id == 99))).scalars().all()
    assert rows == []

    await clear_rls_session_context(db_session)
    ctx = await db_session.execute(text("SELECT current_setting('app.tenant_id', true)"))
    assert ctx.scalar() in ("", None)
