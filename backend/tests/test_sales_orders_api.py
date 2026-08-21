from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.sales_order import SalesOrder
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_list_sales_orders_empty(client: AsyncClient) -> None:
    res = await client.get("/api/sales")
    assert res.status_code == 200
    body = res.json()
    assert body["data"] == []


@pytest.mark.asyncio
async def test_list_sales_orders_returns_register_row(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    so_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="so-demo-1",
        route_target="Sales Management",
        sales_document_type="so",
        so_reference="SO-DEMO-1",
    )
    db_session.add(so_doc)
    await db_session.flush()
    so = SalesOrder(
        tenant_id=TESTING_TENANT_UUID,
        so_number="SO-DEMO-1",
        customer="Harbour View Hotel",
        so_qty=Decimal("4"),
        so_unit_price=Decimal("25"),
        so_document_id=so_doc.id,
    )
    db_session.add(so)
    await db_session.commit()

    res = await client.get("/api/sales")
    assert res.status_code == 200
    rows = res.json()["data"]
    assert len(rows) >= 1
    assert any(r["so_number"] == "SO-DEMO-1" for r in rows)
