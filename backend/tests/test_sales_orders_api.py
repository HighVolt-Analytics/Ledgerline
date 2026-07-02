from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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
    so = SalesOrder(
        tenant_id=TESTING_TENANT_UUID,
        so_number="SO-DEMO-1",
        customer="Harbour View Hotel",
        so_qty=Decimal("4"),
        so_unit_price=Decimal("25"),
    )
    db_session.add(so)
    await db_session.commit()

    res = await client.get("/api/sales")
    assert res.status_code == 200
    rows = res.json()["data"]
    assert len(rows) >= 1
    assert any(r["so_number"] == "SO-DEMO-1" for r in rows)
