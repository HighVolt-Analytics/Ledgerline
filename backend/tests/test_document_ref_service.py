"""Tests for org-scoped document references."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.document_ref_service import assign_document_ref, display_document_ref, next_document_ref


@pytest.mark.asyncio
async def test_assign_document_ref_increments_per_org(db_session: AsyncSession) -> None:
    first = Invoice(org_id=1, status=InvoiceStatus.PENDING, currency="AUD")
    second = Invoice(org_id=1, status=InvoiceStatus.PENDING, currency="AUD")
    db_session.add(first)
    await db_session.flush()
    await assign_document_ref(db_session, first)
    db_session.add(second)
    await db_session.flush()
    await assign_document_ref(db_session, second)

    assert first.document_ref == "DOC-1"
    assert second.document_ref == "DOC-2"


@pytest.mark.asyncio
async def test_next_document_ref_ignores_deleted_gaps(db_session: AsyncSession) -> None:
    existing = Invoice(
        org_id=1,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        document_ref="DOC-3",
    )
    db_session.add(existing)
    await db_session.flush()

    nxt = await next_document_ref(db_session, org_id=1)
    assert nxt == "DOC-4"


def test_display_document_ref_prefers_assigned_value() -> None:
    inv = Invoice(org_id=1, currency="AUD", document_ref="DOC-2")
    inv.id = 93
    assert display_document_ref(inv) == "DOC-2"
