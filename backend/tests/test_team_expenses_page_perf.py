"""Team Expenses operations first-paint regressions (perf/team-expenses-optimization)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.vendor_master import VendorMasterRecord
from app.tenant_ids import TESTING_TENANT_UUID


def _capture_sql(db_session: AsyncSession):
    statements: list[str] = []
    sync_engine = db_session.bind.sync_engine

    def _before_cursor_execute(
        _conn, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        statements.append(str(statement))

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    return statements, lambda: event.remove(
        sync_engine, "before_cursor_execute", _before_cursor_execute
    )


@pytest.mark.asyncio
async def test_rule_book_team_expenses_slice_skips_masters(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        VendorMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="vm-te-page-1",
            name="TE Vendor",
            aliases=[],
            abn="51824753556",
        )
    )
    await db_session.flush()

    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/rule-book/config?fields=team_expenses")
    finally:
        stop()

    assert res.status_code == 200
    body = res.json()["data"]
    assert set(body.keys()) == {"team_expense_rules", "team_expense_posting"}
    assert isinstance(body["team_expense_rules"], list)
    sql = " ".join(statements).lower()
    assert "vendor_masters" not in sql
    assert "employee_masters" not in sql


@pytest.mark.asyncio
async def test_team_expense_routed_list_uses_limit(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Staff Claim",
            status=InvoiceStatus.EXCEPTION,
            currency="AUD",
            file_hash="te-route-1",
            route_target="Team Expenses",
            team_expense_kind="expense_claim",
        )
    )
    await db_session.flush()

    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get(
            "/api/invoices",
            params={
                "page": 1,
                "page_size": 50,
                "route_target": "Team Expenses",
            },
        )
    finally:
        stop()

    assert res.status_code == 200
    assert any(row["route_target"] == "Team Expenses" for row in res.json()["data"])
    invoice_selects = [
        s
        for s in statements
        if "from invoices" in s.lower() and "select" in s.lower() and "count(" not in s.lower()
    ]
    assert any(" limit " in s.lower() for s in invoice_selects), invoice_selects


@pytest.mark.asyncio
async def test_team_expense_list_skips_count_when_include_total_false(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Staff Claim",
            status=InvoiceStatus.EXCEPTION,
            currency="AUD",
            file_hash="te-nocount-1",
            route_target="Team Expenses",
            team_expense_kind="expense_claim",
        )
    )
    await db_session.flush()

    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get(
            "/api/invoices",
            params={
                "page": 1,
                "page_size": 50,
                "route_target": "Team Expenses",
                "include_total": "false",
            },
        )
    finally:
        stop()

    assert res.status_code == 200
    assert res.json()["meta"]["pages"] == 1
    sql = " ".join(statements).lower()
    assert "count(" not in sql


@pytest.mark.asyncio
async def test_team_expense_workspace_kpis(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Open Claim",
            status=InvoiceStatus.EXCEPTION,
            currency="AUD",
            file_hash="te-kpi-open",
            route_target="Team Expenses",
            team_expense_kind="expense_claim",
        )
    )
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Advance",
            status=InvoiceStatus.EXCEPTION,
            currency="AUD",
            file_hash="te-kpi-adv",
            route_target="Team Expenses",
            team_expense_kind="advance_requisition",
        )
    )
    await db_session.flush()

    res = await client.get("/api/reports/team-expenses/workspace-kpis")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["kind_counts"]["expense_claim"] >= 1
    assert body["kind_counts"]["advance_requisition"] >= 1
    assert body["open_count"] >= 2
    assert body["pending_count"] >= 2


@pytest.mark.asyncio
async def test_gl_budget_utilization_does_not_n1_gl_period_consumed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import date
    from decimal import Decimal

    from app.models.department_budget import DepartmentBudget
    from app.services.master_data import department_budget_service as svc
    from app.services.purchase import team_expense_spend_service as spend
    from app.services.purchase.team_expense_spend_service import current_period_keys

    async def _fail(*_args, **_kwargs):
        raise AssertionError("gl_period_consumed should not run for utilization rows")

    monkeypatch.setattr(spend, "gl_period_consumed", _fail)

    keys = current_period_keys(date.today())
    db_session.add(
        DepartmentBudget(
            tenant_id=TESTING_TENANT_UUID,
            department="",
            gl_ledger="Travel",
            period_kind="monthly",
            period_key=keys["monthly"],
            allocated=Decimal("1000"),
        )
    )
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            status=InvoiceStatus.PROCESSED,
            currency="AUD",
            total=Decimal("80"),
            route_target="Team Expenses",
            team_expense_kind="expense_claim",
            file_hash="te-util-batch",
            account_name="Travel",
        )
    )
    await db_session.flush()

    rows = await svc.build_department_budget_utilization_rows(
        db_session, TESTING_TENANT_UUID
    )
    row = next(r for r in rows if r.gl_ledger == "Travel")
    assert row.consumed == 80


def test_team_expense_kind_count_sql_is_postgres_safe() -> None:
    from sqlalchemy.dialects import postgresql

    from app.models.invoice import Invoice
    from app.services.reports.team_expense_reports_service import (
        team_expense_kind_count_stmt,
    )
    from app.tenant_ids import TESTING_TENANT_UUID

    sql = str(
        team_expense_kind_count_stmt(Invoice.tenant_id == TESTING_TENANT_UUID).compile(
            dialect=postgresql.dialect()
        )
    ).lower()
    assert "group by invoices.team_expense_kind" in sql
    assert "lower(" not in sql
    assert "coalesce(" not in sql
