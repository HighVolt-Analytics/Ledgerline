"""Collections first-paint regressions (perf/collections-optimization)."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import Collection, CollectionStatus
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.tenant_ids import TESTING_TENANT_UUID
from app.tenant_settings import tenant_today


async def _add_collection(
    db_session: AsyncSession,
    *,
    status: CollectionStatus,
    amount: str,
    currency: str,
    due_date,
    customer: str = "Harbour View Hotel",
) -> Collection:
    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor=customer,
        status=InvoiceStatus.PROCESSED,
        currency=currency,
        total=Decimal(amount),
        due_date=due_date,
        file_hash=f"col-{uuid4().hex}",
        route_target="Sales Management",
        sales_document_type="invoice",
    )
    db_session.add(invoice)
    await db_session.flush()
    row = Collection(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=invoice.id,
        customer=customer,
        amount=Decimal(amount),
        currency=currency,
        status=status,
        due_date=due_date,
    )
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.mark.asyncio
async def test_collection_kpis_are_not_truncated_to_list(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tenant = await db_session.get(Tenant, TESTING_TENANT_UUID)
    today = tenant_today(tenant)

    await _add_collection(
        db_session,
        status=CollectionStatus.QUEUE,
        amount="100.00",
        currency="AUD",
        due_date=today - timedelta(days=2),
    )
    await _add_collection(
        db_session,
        status=CollectionStatus.AWAITING,
        amount="50.00",
        currency="USD",
        due_date=today + timedelta(days=3),
    )
    await _add_collection(
        db_session,
        status=CollectionStatus.QUEUE,
        amount="25.00",
        currency="AUD",
        due_date=today + timedelta(days=20),
    )
    await _add_collection(
        db_session,
        status=CollectionStatus.RECEIVED,
        amount="999.00",
        currency="AUD",
        due_date=today - timedelta(days=40),
    )

    kpis = (await client.get("/api/collections/kpis")).json()["data"]
    assert kpis["open_count"] == 3
    assert kpis["queue_count"] == 2
    assert kpis["awaiting_count"] == 1
    assert kpis["received_count"] == 1
    assert kpis["failed_count"] == 0
    assert kpis["overdue_count"] == 1
    assert kpis["due_soon_count"] == 1
    assert kpis["outstanding_by_currency"]["AUD"] == 125.0
    assert kpis["outstanding_by_currency"]["USD"] == 50.0

    queued = (await client.get("/api/collections?status=queue&limit=1")).json()["data"]
    assert len(queued) == 1
    assert queued[0]["status"] == "queue"
    # KPIs stay accurate even when the visible list is capped.
    assert kpis["queue_count"] == 2


@pytest.mark.asyncio
async def test_collection_list_status_filter_and_unbounded_compat(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tenant = await db_session.get(Tenant, TESTING_TENANT_UUID)
    today = tenant_today(tenant)

    await _add_collection(
        db_session,
        status=CollectionStatus.QUEUE,
        amount="10.00",
        currency="AUD",
        due_date=today,
        customer="Queue Co",
    )
    await _add_collection(
        db_session,
        status=CollectionStatus.RECEIVED,
        amount="20.00",
        currency="AUD",
        due_date=today,
        customer="Paid Co",
    )

    queued = (await client.get("/api/collections?status=queue")).json()["data"]
    assert [row["customer"] for row in queued] == ["Queue Co"]

    all_rows = (await client.get("/api/collections")).json()["data"]
    assert {row["customer"] for row in all_rows} == {"Queue Co", "Paid Co"}

    bad = await client.get("/api/collections?status=not-a-tab")
    assert bad.status_code == 400
