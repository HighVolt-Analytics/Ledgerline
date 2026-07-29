
from app.tenant_ids import TESTING_TENANT_UUID
"""SO-first sales documents with auto-register from commercial invoice / DN."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus, SalesDocumentType
from app.models.sales_order import SalesOrder
from app.services.invoice.invoice_evaluation_service import ROUTE_SALES
from app.services.sales.sales_document_service import (
    EVAL_AWAITING_SO,
    sync_sales_document,
)


async def _add_line(session: AsyncSession, inv: Invoice, qty: str = "10", price: str = "50") -> Invoice:
    from app.models.line_item import LineItem

    session.add(
        LineItem(
            invoice_id=inv.id,
            description="Widgets",
            qty=Decimal(qty),
            unit_price=Decimal(price),
            amount=Decimal(qty) * Decimal(price),
        )
    )
    await session.flush()
    return (
        await session.execute(
            select(Invoice).where(Invoice.id == inv.id).options(selectinload(Invoice.line_items))
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_so_first_then_commercial_invoice(db_session: AsyncSession) -> None:
    so_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        so_reference="SO-100",
        invoice_no="SO-100",
        route_target=ROUTE_SALES,
        sales_document_type=SalesDocumentType.SO.value,
        subtotal=Decimal("500.00"),
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(so_doc)
    await db_session.flush()
    await _add_line(db_session, so_doc, "10", "50")

    so_row = await sync_sales_document(db_session, so_doc)
    assert so_row is not None
    assert so_row.so_number == "SO-100"
    assert so_row.so_document_id == so_doc.id
    assert so_row.invoice_id is None

    commercial = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        so_reference="SO-100",
        invoice_no="INV-100",
        route_target=ROUTE_SALES,
        sales_document_type=SalesDocumentType.INVOICE.value,
        document_type_code="DT-26",
        subtotal=Decimal("500.00"),
        gst=Decimal("50.00"),
        total=Decimal("550.00"),
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(commercial)
    await db_session.flush()
    await _add_line(db_session, commercial, "10", "50")

    linked = await sync_sales_document(db_session, commercial)
    assert linked is not None
    assert linked.invoice_id == commercial.id
    assert linked.so_document_id == so_doc.id


@pytest.mark.asyncio
async def test_commercial_invoice_holds_awaiting_so_without_register(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        so_reference="SO-200",
        invoice_no="INV-200",
        route_target=ROUTE_SALES,
        sales_document_type=SalesDocumentType.INVOICE.value,
        document_type_code="DT-26",
        subtotal=Decimal("100.00"),
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(inv)
    await db_session.flush()
    await _add_line(db_session, inv)

    result = await sync_sales_document(db_session, inv)
    assert result is None
    assert inv.evaluation_status == EVAL_AWAITING_SO
    assert inv.status == InvoiceStatus.EXCEPTION

    so_count = (
        await db_session.execute(select(SalesOrder).where(SalesOrder.so_number == "SO-200"))
    ).scalar_one_or_none()
    assert so_count is None


@pytest.mark.asyncio
async def test_dn_holds_awaiting_so_without_register(db_session: AsyncSession) -> None:
    dn_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        so_reference="SO-300",
        invoice_no="DN-300",
        route_target=ROUTE_SALES,
        sales_document_type=SalesDocumentType.DN.value,
        document_type_code="DT-26",
        subtotal=Decimal("80.00"),
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(dn_doc)
    await db_session.flush()
    await _add_line(db_session, dn_doc, "8", "10")

    result = await sync_sales_document(db_session, dn_doc)
    assert result is None
    assert dn_doc.evaluation_status == EVAL_AWAITING_SO
    assert dn_doc.status == InvoiceStatus.EXCEPTION

    so_row = (
        await db_session.execute(select(SalesOrder).where(SalesOrder.so_number == "SO-300"))
    ).scalar_one_or_none()
    assert so_row is None
