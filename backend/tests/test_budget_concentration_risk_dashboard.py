"""Reconciliation tests: Budget & concentration risk === Budget Variance / Vendor Spend."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department_budget import DepartmentBudget
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.services.reports.budget_concentration_risk_service import (
    build_budget_concentration_risk_dashboard,
)
from app.services.reports.exception_status_catalog_builders import _parse_money
from app.services.reports.position_liquidity_service import (
    _fy_window,
    build_position_liquidity_dashboard,
)
from app.services.reports.statement_builders import _build_budget_variance
from app.services.reports.report_catalog import CATALOG_BY_ID
from app.tenant_ids import TESTING_TENANT_UUID
from tests.auth_test_helpers import seed_admin_user, tenant_auth_headers

TENANT_A_ID = UUID("55555555-5555-4555-8555-555555555501")
TENANT_B_ID = UUID("55555555-5555-4555-8555-555555555502")


@pytest.mark.asyncio
async def test_budget_concentration_risk_api_empty(client: AsyncClient) -> None:
    res = await client.get("/api/dashboard/budget-concentration-risk")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["departments"] == []
    assert body["vendors"] == []
    assert Decimal(body["budget_summary"]["budget"]) == Decimal("0")
    assert body["vendor_summary"]["top10_concentration_pct"] is None


@pytest.mark.asyncio
async def test_department_budget_aggregates_by_department_label(
    db_session: AsyncSession,
) -> None:
    today = date.today()
    period_key = f"{today.year:04d}-{today.month:02d}"
    db_session.add(
        DepartmentBudget(
            tenant_id=TESTING_TENANT_UUID,
            department="Operations",
            gl_ledger="6100",
            period_kind="monthly",
            period_key=period_key,
            allocated=Decimal("10000.00"),
        )
    )
    await db_session.commit()

    dash = await build_budget_concentration_risk_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    ops = next((row for row in dash.departments if row.name == "Operations"), None)
    assert ops is not None
    assert ops.budget == Decimal("10000.00")


@pytest.mark.asyncio
async def test_budget_summary_reconciles_with_budget_variance_report(
    db_session: AsyncSession,
) -> None:
    today = date.today()
    period_key = f"{today.year:04d}-{today.month:02d}"
    db_session.add(
        DepartmentBudget(
            tenant_id=TESTING_TENANT_UUID,
            department="Operations",
            gl_ledger="6100",
            period_kind="monthly",
            period_key=period_key,
            allocated=Decimal("10000.00"),
        )
    )
    await db_session.commit()

    dash = await build_budget_concentration_risk_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    period_start, period_end, _ = _fy_window(today)
    preview = await _build_budget_variance(
        db_session,
        TESTING_TENANT_UUID,
        CATALOG_BY_ID["budget-variance"],
        period_start,
        period_end,
        compare=False,
        as_of=True,
    )
    total_row = next(row for row in preview.rows if row.emphasize)
    budget_idx = preview.columns.index("Budget")
    actual_idx = preview.columns.index("Actual")
    committed_idx = preview.columns.index("Committed")
    assert dash.budget_summary.budget == _parse_money(total_row.cells[budget_idx])
    assert dash.budget_summary.actual == _parse_money(total_row.cells[actual_idx])
    assert dash.budget_summary.committed == _parse_money(total_row.cells[committed_idx])


@pytest.mark.asyncio
async def test_vendor_concentration_reconciles_with_position_liquidity(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Pareto Vendor",
        invoice_no="PVR-1",
        invoice_date=date.today(),
        due_date=date.today(),
        subtotal=Decimal("500.00"),
        gst=Decimal("0"),
        total=Decimal("500.00"),
        currency="AUD",
        status=InvoiceStatus.PROCESSED,
        file_hash="bcr-pareto-1",
    )
    db_session.add(inv)
    await db_session.commit()

    dash = await build_budget_concentration_risk_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    liquidity = await build_position_liquidity_dashboard(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert dash.vendor_summary.top10_concentration_pct == liquidity.kpis.vendor_top10_concentration_pct
    assert dash.vendor_summary.non_po_spend_pct == liquidity.kpis.vendor_non_po_spend_pct
    assert len(dash.vendors) == 1
    assert dash.vendors[0].name == "Pareto Vendor"
    assert dash.vendors[0].spend == Decimal("500.00")


@pytest.mark.asyncio
async def test_budget_concentration_risk_does_not_leak_across_tenants(
    db_session: AsyncSession,
    client: AsyncClient,
) -> None:
    for tenant_id, slug, name in (
        (TENANT_A_ID, "bcr-a", "BCR Tenant A"),
        (TENANT_B_ID, "bcr-b", "BCR Tenant B"),
    ):
        db_session.add(Tenant(id=tenant_id, slug=slug, name=name))
    inv_a = Invoice(
        tenant_id=TENANT_A_ID,
        vendor="Tenant A Vendor",
        invoice_no="A-1",
        invoice_date=date.today(),
        due_date=date.today(),
        subtotal=Decimal("900.00"),
        gst=Decimal("0"),
        total=Decimal("900.00"),
        currency="AUD",
        status=InvoiceStatus.PROCESSED,
        file_hash="bcr-tenant-a",
    )
    inv_b = Invoice(
        tenant_id=TENANT_B_ID,
        vendor="Tenant B Vendor",
        invoice_no="B-1",
        invoice_date=date.today(),
        due_date=date.today(),
        subtotal=Decimal("1200.00"),
        gst=Decimal("0"),
        total=Decimal("1200.00"),
        currency="AUD",
        status=InvoiceStatus.PROCESSED,
        file_hash="bcr-tenant-b",
    )
    db_session.add_all([inv_a, inv_b])
    await db_session.commit()
    _user_a, token_a = await seed_admin_user(
        db_session,
        email="bcr-a@example.com",
        tenant_id=TENANT_A_ID,
        tenant_slug="bcr-a",
    )
    _user_b, token_b = await seed_admin_user(
        db_session,
        email="bcr-b@example.com",
        tenant_id=TENANT_B_ID,
        tenant_slug="bcr-b",
    )
    await db_session.commit()

    res_a = await client.get(
        "/api/dashboard/budget-concentration-risk",
        headers=tenant_auth_headers(token_a, TENANT_A_ID),
    )
    res_b = await client.get(
        "/api/dashboard/budget-concentration-risk",
        headers=tenant_auth_headers(token_b, TENANT_B_ID),
    )
    assert res_a.status_code == 200
    assert res_b.status_code == 200
    vendors_a = {row["name"] for row in res_a.json()["data"]["vendors"]}
    vendors_b = {row["name"] for row in res_b.json()["data"]["vendors"]}
    assert vendors_a == {"Tenant A Vendor"}
    assert vendors_b == {"Tenant B Vendor"}
