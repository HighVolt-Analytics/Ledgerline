"""Regression: line-item response builder rebinds detached invoice rows."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.invoices import _line_items_response
from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_line_items_response_rebinds_detached_invoice(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        invoice_no="INV-DETACH",
        document_type_code="DT-13",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="detach-1",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            description="Widget",
            amount=Decimal("10.00"),
        )
    )
    await db_session.flush()
    db_session.expunge(inv)

    items = await _line_items_response(db_session, inv, tenant_id=TESTING_TENANT_UUID)

    assert len(items) == 1
    assert items[0].description == "Widget"
