from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import Collection
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment
from app.services.integration.collection_service import ensure_receivable_for_invoice
from app.services.invoice.invoice_evaluation_service import ROUTE_EXPENSES, ROUTE_PURCHASE, ROUTE_SALES
from app.services.payments.payment_service import ensure_payment_for_invoice
from app.services.purchase.purchase_document_service import is_commercial_purchase_invoice
from app.tenant_ids import TESTING_TENANT_UUID


def test_is_commercial_purchase_invoice_rejects_sales_route() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_SALES,
        purchase_document_type=None,
        status=InvoiceStatus.PROCESSED,
    )
    assert not is_commercial_purchase_invoice(inv)


def test_is_commercial_purchase_invoice_accepts_purchase_route() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_PURCHASE,
        purchase_document_type=None,
        status=InvoiceStatus.PROCESSED,
    )
    assert is_commercial_purchase_invoice(inv)


def test_is_commercial_purchase_invoice_accepts_expenses_route() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_EXPENSES,
        purchase_document_type=None,
        status=InvoiceStatus.PROCESSED,
    )
    assert is_commercial_purchase_invoice(inv)


@pytest.mark.asyncio
async def test_sales_processed_invoice_creates_collection_not_payment(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Customer",
        invoice_no="SINV-100",
        total=Decimal("2200.00"),
        due_date=date(2026, 8, 1),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        route_target=ROUTE_SALES,
        sales_document_type="invoice",
        file_hash="sales-settlement",
    )
    db_session.add(inv)
    await db_session.flush()

    payment = await ensure_payment_for_invoice(db_session, inv)
    collection = await ensure_receivable_for_invoice(db_session, inv)
    await db_session.flush()

    assert payment is None
    assert collection is not None
    assert collection.invoice_id == inv.id

    payment_rows = (
        await db_session.execute(
            select(Payment).where(
                Payment.tenant_id == inv.tenant_id,
                Payment.invoice_id == inv.id,
            )
        )
    ).scalars().all()
    collection_rows = (
        await db_session.execute(
            select(Collection).where(
                Collection.tenant_id == inv.tenant_id,
                Collection.invoice_id == inv.id,
            )
        )
    ).scalars().all()
    assert payment_rows == []
    assert len(collection_rows) == 1
