"""Reconciliation tests: Cash & liability outlook === Cash Forecast / Aged Payables."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType
from app.models.payment import Payment, PaymentStatus
from app.models.tenant import Tenant
from app.services.reports.cash_liability_outlook_service import (
    build_cash_liability_outlook_dashboard,
)
from app.services.reports.payables_catalog_builders import build_cash_forecast
from app.services.reports.report_catalog import CATALOG_BY_ID
from app.tenant_ids import TESTING_TENANT_UUID
from tests.auth_test_helpers import seed_admin_user, tenant_auth_headers
from tests.journal_test_helpers import seed_journal_batch

TENANT_A_ID = UUID("44444444-4444-4444-8444-444444444401")
TENANT_B_ID = UUID("44444444-4444-4444-8444-444444444402")


async def _invoice(db: AsyncSession, **kwargs) -> Invoice:
    payload = {
        "tenant_id": TESTING_TENANT_UUID,
        "vendor": "Cash Co",
        "invoice_no": "CLO-1",
        "invoice_date": date.today(),
        "due_date": date.today() + timedelta(days=10),
        "subtotal": Decimal("100.00"),
        "gst": Decimal("0"),
        "total": Decimal("100.00"),
        "currency": "AUD",
        "status": InvoiceStatus.PROCESSED,
        "file_hash": kwargs.pop("file_hash", f"clo-{id(kwargs)}"),
    }
    payload.update(kwargs)
    inv = Invoice(**payload)
    db.add(inv)
    await db.flush()
    return inv


async def _journal(db: AsyncSession, invoice: Invoice, *, credit: Decimal) -> None:
    await seed_journal_batch(
        db,
        invoice,
        [
            (
                "2000",
                "Accounts Payable",
                Decimal("0"),
                credit,
                EntryType.CREDIT,
            )
        ],
        entry_date=invoice.invoice_date or date.today(),
    )


@pytest.mark.asyncio
async def test_cash_liability_outlook_api_empty(client: AsyncClient) -> None:
    res = await client.get("/api/dashboard/cash-liability-outlook")
    assert res.status_code == 200
    body = res.json()["data"]
    assert len(body["weeks"]) == 13
    assert body["summary"]["total_horizon_outflow"] == "0.00"


@pytest.mark.asyncio
async def test_confirmed_ap_uses_scheduled_payment_date(
    db_session: AsyncSession,
) -> None:
    as_of = date.today()
    inv = await _invoice(
        db_session,
        file_hash="clo-conf",
        due_date=as_of + timedelta(days=30),
        total=Decimal("250.00"),
    )
    await _journal(db_session, inv, credit=Decimal("250.00"))
    db_session.add(
        Payment(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            vendor=inv.vendor,
            amount=Decimal("250.00"),
            currency="AUD",
            status=PaymentStatus.SCHEDULED,
            scheduled_date=as_of + timedelta(days=14),
        )
    )
    await db_session.commit()

    dash = await build_cash_liability_outlook_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    week2 = dash.weeks[2]
    assert week2.confirmed_ap == Decimal("250.00")
    assert week2.probable_ap == Decimal("0.00")


@pytest.mark.asyncio
async def test_probable_ap_uses_due_date_without_schedule(
    db_session: AsyncSession,
) -> None:
    as_of = date.today()
    inv = await _invoice(
        db_session,
        file_hash="clo-prob",
        due_date=as_of + timedelta(days=5),
        total=Decimal("80.00"),
    )
    await _journal(db_session, inv, credit=Decimal("80.00"))
    await db_session.commit()

    dash = await build_cash_liability_outlook_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert dash.weeks[0].probable_ap == Decimal("80.00")


@pytest.mark.asyncio
async def test_ap_outflows_reconcile_with_cash_forecast(
    db_session: AsyncSession,
) -> None:
    as_of = date.today()
    overdue = await _invoice(
        db_session,
        file_hash="clo-fc-od",
        due_date=as_of - timedelta(days=3),
        total=Decimal("40.00"),
    )
    upcoming = await _invoice(
        db_session,
        file_hash="clo-fc-up",
        due_date=as_of + timedelta(days=12),
        total=Decimal("60.00"),
    )
    await _journal(db_session, overdue, credit=Decimal("40.00"))
    await _journal(db_session, upcoming, credit=Decimal("60.00"))
    await db_session.commit()

    dash = await build_cash_liability_outlook_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    forecast = await build_cash_forecast(
        db_session, TESTING_TENANT_UUID, CATALOG_BY_ID["cash-forecast"], as_of
    )
    ap_total = sum(
        (w.confirmed_ap + w.probable_ap for w in dash.weeks),
        Decimal("0"),
    )
    forecast_total = Decimal("0")
    amt_idx = forecast.columns.index("Amount due")
    for row in forecast.rows:
        if row.emphasize:
            continue
        forecast_total += Decimal(row.cells[amt_idx].replace(",", ""))
    assert ap_total == forecast_total


@pytest.mark.asyncio
async def test_ap_ageing_reconciles_with_aged_payables(
    db_session: AsyncSession,
) -> None:
    as_of = date.today()
    inv = await _invoice(
        db_session,
        file_hash="clo-age",
        due_date=as_of - timedelta(days=45),
        total=Decimal("120.00"),
    )
    await _journal(db_session, inv, credit=Decimal("120.00"))
    await db_session.commit()

    dash = await build_cash_liability_outlook_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert dash.ap_ageing_total == Decimal("120.00")
    bucket_sum = sum((b.amount for b in dash.ap_ageing), Decimal("0"))
    assert bucket_sum == dash.ap_ageing_total


@pytest.mark.asyncio
async def test_cash_liability_outlook_does_not_leak_across_tenants(
    anon_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    db_session.add(
        Tenant(
            id=TENANT_A_ID,
            name="Cash A",
            slug="cash-iso-a",
            currency="AUD",
            is_active=True,
        )
    )
    db_session.add(
        Tenant(
            id=TENANT_B_ID,
            name="Cash B",
            slug="cash-iso-b",
            currency="AUD",
            is_active=True,
        )
    )
    for tenant_id, amount, tag in (
        (TENANT_A_ID, Decimal("100.00"), "a"),
        (TENANT_B_ID, Decimal("900.00"), "b"),
    ):
        inv = Invoice(
            tenant_id=tenant_id,
            vendor="Iso",
            invoice_no=f"CLO-ISO-{tag}",
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=3),
            total=amount,
            currency="AUD",
            status=InvoiceStatus.PROCESSED,
            file_hash=f"clo-iso-{tag}",
        )
        db_session.add(inv)
        await db_session.flush()
        await seed_journal_batch(
            db_session,
            inv,
            [("2000", "AP", Decimal("0"), amount, EntryType.CREDIT)],
            entry_date=date.today(),
        )
    _user_a, token_a = await seed_admin_user(
        db_session,
        email="cash-iso-a@test.example.com",
        tenant_id=TENANT_A_ID,
        tenant_slug="cash-iso-a",
    )
    _user_b, token_b = await seed_admin_user(
        db_session,
        email="cash-iso-b@test.example.com",
        tenant_id=TENANT_B_ID,
        tenant_slug="cash-iso-b",
    )
    await db_session.commit()

    res_a = await anon_client.get(
        "/api/dashboard/cash-liability-outlook",
        headers=tenant_auth_headers(token_a, TENANT_A_ID),
    )
    res_b = await anon_client.get(
        "/api/dashboard/cash-liability-outlook",
        headers=tenant_auth_headers(token_b, TENANT_B_ID),
    )
    assert res_a.json()["data"]["summary"]["total_horizon_outflow"] == "100.00"
    assert res_b.json()["data"]["summary"]["total_horizon_outflow"] == "900.00"
