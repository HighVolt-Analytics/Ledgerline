"""Defense-in-depth tenant checks on invoice API response builders."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice.invoice_response_service import (
    InvoiceTenantScopeError,
    assert_invoice_tenant_scope,
    response_for_invoice,
)
from tests.conftest import TESTING_TENANT_UUID


def test_assert_invoice_tenant_scope_accepts_matching_rows() -> None:
    tenant_id = TESTING_TENANT_UUID
    row = Invoice(tenant_id=tenant_id, vendor="Acme", status=InvoiceStatus.PENDING)
    assert_invoice_tenant_scope([row], tenant_id)


def test_assert_invoice_tenant_scope_rejects_mismatch() -> None:
    tenant_id = TESTING_TENANT_UUID
    other = uuid.uuid4()
    row = Invoice(tenant_id=other, vendor="Acme", status=InvoiceStatus.PENDING)
    with pytest.raises(InvoiceTenantScopeError):
        assert_invoice_tenant_scope([row], tenant_id)


@pytest.mark.asyncio
async def test_response_for_invoice_reattaches_detached_invoice(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="detach-1",
    )
    db_session.add(inv)
    await db_session.flush()
    await db_session.refresh(inv)
    inv_id = inv.id

    db_session.expunge(inv)

    resp = await response_for_invoice(db_session, inv, tenant_id=TESTING_TENANT_UUID)
    assert resp.id == inv_id
    assert resp.vendor == "Acme"
