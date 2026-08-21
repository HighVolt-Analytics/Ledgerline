"""Expenses Management first-paint regressions (perf/expenses-optimization)."""

from decimal import Decimal

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
async def test_rule_book_expense_rules_slice_skips_masters(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        VendorMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="vm-exp-page-1",
            name="Expense Vendor",
            aliases=[],
            abn="51824753556",
        )
    )
    await db_session.flush()

    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/rule-book/config?fields=expense_rules")
    finally:
        stop()

    assert res.status_code == 200
    body = res.json()["data"]
    assert set(body.keys()) == {"expense_rules"}
    assert isinstance(body["expense_rules"], list)
    sql = " ".join(statements).lower()
    assert "vendor_masters" not in sql
    assert "employee_masters" not in sql


@pytest.mark.asyncio
async def test_expenses_list_skips_count_when_include_total_false(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Utility Co",
            status=InvoiceStatus.EXCEPTION,
            currency="AUD",
            file_hash="exp-nocount-1",
            route_target="Expenses Management",
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
                "route_target": "Expenses Management",
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
async def test_expenses_workspace_kpis(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Open Utility",
            status=InvoiceStatus.EXCEPTION,
            currency="AUD",
            total=Decimal("40.00"),
            file_hash="exp-kpi-open",
            route_target="Expenses Management",
        )
    )
    await db_session.flush()

    res = await client.get("/api/reports/expenses/workspace-kpis")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["open_count"] >= 1
    assert body["pending_count"] >= 1
    assert body["kind_counts"] == {}
