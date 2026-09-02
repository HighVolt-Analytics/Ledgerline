"""Reconciliation tests: CFO alerts === Control Centre + KPI thresholds."""

from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.services.reports.cfo_alerts_service import build_cfo_alerts_dashboard
from app.services.reports.exception_status_catalog_builders import (
    _preview_maps,
    build_control_centre,
)
from app.services.reports.report_catalog import CATALOG_BY_ID
from app.tenant_ids import TESTING_TENANT_UUID
from tests.auth_test_helpers import seed_admin_user, tenant_auth_headers

TENANT_A_ID = UUID("55555555-5555-4555-8555-555555555501")
TENANT_B_ID = UUID("55555555-5555-4555-8555-555555555502")


@pytest.mark.asyncio
async def test_cfo_alerts_api_empty(client: AsyncClient) -> None:
    res = await client.get("/api/dashboard/cfo-alerts")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["summary"]["active_count"] == len(body["alerts"])
    assert body["alerts"] == []


@pytest.mark.asyncio
async def test_control_centre_rows_surface_as_alerts(db_session: AsyncSession) -> None:
    dash = await build_cfo_alerts_dashboard(db_session, tenant_id=TESTING_TENANT_UUID)
    start = date.fromisoformat(dash.meta.period_start)
    end = date.fromisoformat(dash.meta.period_end)
    preview = await build_control_centre(
        db_session,
        TESTING_TENANT_UUID,
        CATALOG_BY_ID["control-centre"],
        start,
        end,
        as_of=True,
    )
    control_items = _preview_maps(preview)
    control_alerts = [row for row in dash.alerts if row.source == "control_centre"]
    assert len(control_alerts) == len(control_items)


@pytest.mark.asyncio
async def test_cfo_alerts_tenant_isolation(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    for tenant_id, slug, name in (
        (TENANT_A_ID, "alerts-a", "Alerts Tenant A"),
        (TENANT_B_ID, "alerts-b", "Alerts Tenant B"),
    ):
        db_session.add(Tenant(id=tenant_id, slug=slug, name=name))
    await db_session.flush()

    _user_a, token_a = await seed_admin_user(
        db_session,
        email="alerts-a@example.com",
        tenant_id=TENANT_A_ID,
        tenant_slug="alerts-a",
    )
    _user_b, token_b = await seed_admin_user(
        db_session,
        email="alerts-b@example.com",
        tenant_id=TENANT_B_ID,
        tenant_slug="alerts-b",
    )
    await db_session.commit()

    res_a = await client.get(
        "/api/dashboard/cfo-alerts",
        headers=tenant_auth_headers(token_a, TENANT_A_ID),
    )
    res_b = await client.get(
        "/api/dashboard/cfo-alerts",
        headers=tenant_auth_headers(token_b, TENANT_B_ID),
    )
    assert res_a.status_code == 200
    assert res_b.status_code == 200
    assert res_a.json()["data"]["summary"]["active_count"] == 0
    assert res_b.json()["data"]["summary"]["active_count"] == 0
