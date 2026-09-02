"""Reconciliation tests: Process efficiency trends === Position & Liquidity DPO + Process Efficiency STP."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.services.reports.exception_status_catalog_builders import process_efficiency_slice
from app.services.reports.position_liquidity_service import _compute_dpo
from app.services.reports.process_efficiency_trends_service import (
    _rolling_month_windows,
    build_process_efficiency_trends_dashboard,
)
from app.tenant_ids import TESTING_TENANT_UUID
from app.tenant_settings import tenant_currency

TENANT_B_ID = UUID("55555555-5555-4555-8555-555555555502")


@pytest.mark.asyncio
async def test_process_efficiency_trends_api_empty(client: AsyncClient) -> None:
    res = await client.get("/api/dashboard/process-efficiency-trends")
    assert res.status_code == 200
    body = res.json()["data"]
    assert len(body["points"]) == 12
    assert Decimal(body["summary"]["stp_target_pct"]) == Decimal("85")
    assert body["summary"]["months_with_dpo"] == 0
    assert body["summary"]["months_with_stp"] == 0


@pytest.mark.asyncio
async def test_rolling_month_windows_count_and_order() -> None:
    as_of = date(2026, 3, 15)
    windows = _rolling_month_windows(as_of)
    assert len(windows) == 12
    assert windows[0][0] == date(2025, 4, 1)
    assert windows[-1][1] == as_of


@pytest.mark.asyncio
async def test_stp_point_reconciles_with_process_efficiency_slice(
    db_session: AsyncSession,
) -> None:
    today = date.today()
    month_start = today.replace(day=1)
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            status=InvoiceStatus.PROCESSED,
            vendor="Trend Vendor",
            total=Decimal("100.00"),
            currency="AUD",
            created_at=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
        )
    )
    await db_session.commit()

    dash = await build_process_efficiency_trends_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    latest = dash.points[-1]
    expected = await process_efficiency_slice(
        db_session, TESTING_TENANT_UUID, month_start, today
    )
    assert latest.stp_pct == expected.stp_pct


@pytest.mark.asyncio
async def test_dpo_point_reconciles_with_position_liquidity_formula(
    db_session: AsyncSession,
) -> None:
    today = date.today()
    month_start = today.replace(day=1)
    tenant = await db_session.get(Tenant, TESTING_TENANT_UUID)
    base = tenant_currency(tenant)

    dash = await build_process_efficiency_trends_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    latest = dash.points[-1]
    expected = await _compute_dpo(
        db_session, TESTING_TENANT_UUID, month_start, today, base=base
    )
    assert latest.dpo_days == expected


@pytest.mark.asyncio
async def test_process_efficiency_trends_tenant_isolated(
    db_session: AsyncSession,
) -> None:
    today = date.today()
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            status=InvoiceStatus.PROCESSED,
            vendor="Tenant A Vendor",
            total=Decimal("250.00"),
            currency="AUD",
            created_at=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
        )
    )
    await db_session.commit()

    dash_a = await build_process_efficiency_trends_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    dash_b = await build_process_efficiency_trends_dashboard(
        db_session, tenant_id=TENANT_B_ID
    )
    assert dash_a.summary.months_with_stp >= 1
    assert dash_b.summary.months_with_stp == 0
