"""Tests for org-scoped document references."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.document_ref_service import (
    assign_document_ref,
    display_document_ref,
    dossier_public_id,
    next_document_ref,
    parse_dossier_id_token,
)


@pytest.mark.asyncio
async def test_assign_document_ref_increments_per_org(db_session: AsyncSession) -> None:
    first = Invoice(tenant_id=1, status=InvoiceStatus.PENDING, currency="AUD")
    second = Invoice(tenant_id=1, status=InvoiceStatus.PENDING, currency="AUD")
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
        tenant_id=1,
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        document_ref="DOC-3",
    )
    db_session.add(existing)
    await db_session.flush()

    nxt = await next_document_ref(db_session, tenant_id=1)
    assert nxt == "DOC-4"


def test_display_document_ref_prefers_assigned_value() -> None:
    inv = Invoice(tenant_id=1, currency="AUD", document_ref="DOC-2")
    inv.id = 93
    assert display_document_ref(inv) == "DOC-2"


def test_dossier_public_id_uses_assigned_ref() -> None:
    inv = Invoice(tenant_id=1, currency="AUD", document_ref="DOC-2")
    inv.id = 93
    assert dossier_public_id(inv) == "DOC-2"


def test_dossier_public_id_fallback_uses_invoice_id() -> None:
    inv = Invoice(tenant_id=1, currency="AUD")
    inv.id = 93
    assert dossier_public_id(inv) == "DOC-93"


def test_parse_dossier_id_token() -> None:
    assert parse_dossier_id_token("133") == (None, 133)
    assert parse_dossier_id_token("DOC-18") == ("DOC-18", 18)
    assert parse_dossier_id_token("doc-18") == ("doc-18", 18)
    assert parse_dossier_id_token("") == (None, None)
