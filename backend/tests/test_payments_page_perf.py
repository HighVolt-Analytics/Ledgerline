"""Payments first-paint regressions (perf/payments-optimization)."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.models.tenant import Tenant
from app.tenant_ids import TESTING_TENANT_UUID
from app.tenant_settings import tenant_today


async def _add_payment(
    db_session: AsyncSession,
    *,
    status: PaymentStatus,
    amount: str,
    currency: str,
    due_date,
    vendor: str = "Vendor Pay",
) -> Payment:
    invoice = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor=vendor,
        status=InvoiceStatus.PROCESSED,
        currency=currency,
        total=Decimal(amount),
        due_date=due_date,
        file_hash=f"pay-{uuid4().hex}",
        route_target="Purchase Management",
    )
    db_session.add(invoice)
    await db_session.flush()
    row = Payment(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=invoice.id,
        vendor=vendor,
        amount=Decimal(amount),
        currency=currency,
        status=status,
        due_date=due_date,
    )
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.mark.asyncio
async def test_payment_kpis_are_not_truncated_to_list(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tenant = await db_session.get(Tenant, TESTING_TENANT_UUID)
    today = tenant_today(tenant)

    await _add_payment(
        db_session,
        status=PaymentStatus.QUEUE,
        amount="100.00",
        currency="AUD",
        due_date=today - timedelta(days=2),
    )
    await _add_payment(
        db_session,
        status=PaymentStatus.AWAITING,
        amount="50.00",
        currency="USD",
        due_date=today + timedelta(days=3),
    )
    await _add_payment(
        db_session,
        status=PaymentStatus.SCHEDULED,
        amount="25.00",
        currency="AUD",
        due_date=today + timedelta(days=20),
    )
    await _add_payment(
        db_session,
        status=PaymentStatus.PAID,
        amount="999.00",
        currency="AUD",
        due_date=today - timedelta(days=40),
    )

    kpis = (await client.get("/api/payments/kpis")).json()["data"]
    assert kpis["open_count"] == 3
    assert kpis["queue_count"] == 1
    assert kpis["awaiting_count"] == 1
    assert kpis["scheduled_count"] == 1
    assert kpis["paid_count"] == 1
    assert kpis["failed_count"] == 0
    assert kpis["overdue_count"] == 1
    assert kpis["due_soon_count"] == 1
    assert kpis["outstanding_by_currency"]["AUD"] == 125.0
    assert kpis["outstanding_by_currency"]["USD"] == 50.0

    queued = (await client.get("/api/payments?status=queue&limit=1")).json()["data"]
    assert len(queued) == 1
    assert queued[0]["status"] == "queue"
    assert kpis["queue_count"] == 1


@pytest.mark.asyncio
async def test_payment_list_status_filter_and_unbounded_compat(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tenant = await db_session.get(Tenant, TESTING_TENANT_UUID)
    today = tenant_today(tenant)

    await _add_payment(
        db_session,
        status=PaymentStatus.QUEUE,
        amount="10.00",
        currency="AUD",
        due_date=today,
        vendor="Queue Co",
    )
    await _add_payment(
        db_session,
        status=PaymentStatus.PAID,
        amount="20.00",
        currency="AUD",
        due_date=today,
        vendor="Paid Co",
    )

    queued = (await client.get("/api/payments?status=queue")).json()["data"]
    assert [row["vendor"] for row in queued] == ["Queue Co"]

    all_rows = (await client.get("/api/payments")).json()["data"]
    assert {row["vendor"] for row in all_rows} == {"Queue Co", "Paid Co"}

    bad = await client.get("/api/payments?status=not-a-tab")
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_wallet_summary_does_not_need_every_payment_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tenant = await db_session.get(Tenant, TESTING_TENANT_UUID)
    today = tenant_today(tenant)
    await _add_payment(
        db_session,
        status=PaymentStatus.QUEUE,
        amount="40.00",
        currency="AUD",
        due_date=today,
        vendor="Open Co",
    )
    await _add_payment(
        db_session,
        status=PaymentStatus.PAID,
        amount="10.00",
        currency="AUD",
        due_date=today,
        vendor="Paid Co",
    )

    res = await client.get("/api/payments/wallet-summary")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["available"] == 40.0
    assert data["balance"] == 50.0
    assert {row["label"] for row in data["transactions"]} <= {
        "Open Co queued",
        "Paid Co payment",
    }
