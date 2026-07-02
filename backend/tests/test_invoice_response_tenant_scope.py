"""Defense-in-depth tenant checks on invoice API response builders."""

import uuid

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice_response_service import (
    InvoiceTenantScopeError,
    assert_invoice_tenant_scope,
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
