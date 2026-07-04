from decimal import Decimal
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.integration.collection_service import ensure_receivable_for_invoice
from app.services.invoice.invoice_evaluation_service import ROUTE_SALES
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_ensure_receivable_for_sales_invoice(db_session: AsyncSession) -> None:
    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        invoice_no="INV-OUT-900",
        route_target=ROUTE_SALES,
        sales_document_type="invoice",
        status=InvoiceStatus.PROCESSED,
        due_date=date(2026, 6, 30),
        total=Decimal("1100.00"),
        currency="AUD",
    )
    db_session.add(invoice)
    await db_session.flush()

    row = await ensure_receivable_for_invoice(db_session, invoice)
    assert row is not None
    assert row.invoice_id == invoice.id
    assert float(row.amount) == 1100.0

    again = await ensure_receivable_for_invoice(db_session, invoice)
    assert again is not None
    assert again.id == row.id


@pytest.mark.asyncio
async def test_ensure_receivable_skips_non_sales(db_session: AsyncSession) -> None:
    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Supplier Co",
        route_target="Purchase Management",
        status=InvoiceStatus.PROCESSED,
        due_date=date(2026, 6, 30),
        total=Decimal("500.00"),
    )
    db_session.add(invoice)
    await db_session.flush()
    assert await ensure_receivable_for_invoice(db_session, invoice) is None
