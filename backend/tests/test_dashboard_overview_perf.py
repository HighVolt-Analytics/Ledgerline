"""Dashboard overview query-volume regressions (perf/dashboard-optimization)."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.tenant_ids import TESTING_TENANT_UUID


def test_invoices_from_loaded_windows_covers_month_7d_30d() -> None:
    from app.services.reports.dashboard_panels_service import (
        _invoices_from_loaded_windows,
    )

    today = date(2026, 8, 21)
    month_start = date(2026, 8, 1)
    month_end = date(2026, 8, 31)
    prior_start = date(2026, 7, 1)
    prior_end = date(2026, 7, 31)
    august = SimpleNamespace(
        created_at=datetime(2026, 8, 20, tzinfo=timezone.utc)
    )
    july = SimpleNamespace(
        created_at=datetime(2026, 7, 25, tzinfo=timezone.utc)
    )
    loaded = [
        (month_start, month_end, [august]),
        (prior_start, prior_end, [july]),
    ]

    month_rows = _invoices_from_loaded_windows(month_start, month_end, loaded)
    assert month_rows is not None
    assert august in month_rows
    assert july not in month_rows

    seven = _invoices_from_loaded_windows(
        today - timedelta(days=6), today, loaded
    )
    assert seven is not None
    assert august in seven

    thirty = _invoices_from_loaded_windows(
        today - timedelta(days=29), today, loaded
    )
    assert thirty is not None
    assert august in thirty
    assert july in thirty

    assert (
        _invoices_from_loaded_windows(
            date(2026, 1, 1), date(2026, 1, 31), loaded
        )
        is None
    )


@pytest.mark.asyncio
async def test_overview_does_not_call_unused_builders(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.reports import dashboard_service as svc

    async def fail(*_args, **_kwargs):
        raise AssertionError("unused overview builder must not run")

    monkeypatch.setattr(svc, "fetch_activity", fail)
    monkeypatch.setattr(svc, "fetch_anomalies", fail)
    monkeypatch.setattr(svc, "fetch_mailbox_breakdown", fail)
    monkeypatch.setattr(svc, "build_kpi_trends", fail)
    monkeypatch.setattr(svc, "fetch_kpi_sparklines", fail)

    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Perf Co",
            total=Decimal("10.00"),
            status=InvoiceStatus.PROCESSED,
            currency="AUD",
            file_hash="dash-perf-unused",
        )
    )
    await db_session.flush()

    res = await client.get("/api/dashboard/overview")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["activity"] == []
    assert body["anomalies"] == []
    assert body["mailbox_breakdown"] == []
    assert body["kpi_trends"] == {}
    assert body["top_vendors"][0]["vendor"] == "Perf Co"


@pytest.mark.asyncio
async def test_overview_sql_statement_count_stays_bounded(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Regression ceiling: unused overview work used to add dozens of extra SQL round-trips."""
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Count Co",
            total=Decimal("25.00"),
            status=InvoiceStatus.PROCESSED,
            currency="AUD",
            file_hash="dash-perf-count",
        )
    )
    await db_session.flush()

    statements: list[str] = []
    sync_engine = db_session.bind.sync_engine

    def _before_cursor_execute(
        _conn, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        statements.append(str(statement))

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        res = await client.get("/api/dashboard/overview")
        assert res.status_code == 200
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)

    # Auth + RLS + stats + panels + vendors + forecast. Keep a ceiling so
    # activity/sparklines/trends/mailbox N+1 cannot silently return.
    assert 1 <= len(statements) <= 55, len(statements)
    mailbox_from = sum(
        1
        for s in statements
        if "from connected_mailboxes" in str(s).lower()
    )
    assert mailbox_from <= 2, mailbox_from


def test_gzip_middleware_skipped_in_local_app_env() -> None:
    from starlette.middleware.gzip import GZipMiddleware

    from app.config import get_settings
    from app.main import app

    env = get_settings().app_env.strip().lower()
    present = any(m.cls is GZipMiddleware for m in app.user_middleware)
    if env in {"production", "prod", "preview", "staging", "stage", "ledgerlink"}:
        assert present
    else:
        assert not present


@pytest.mark.asyncio
async def test_badges_sql_statement_count_stays_bounded(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    statements: list[str] = []
    sync_engine = db_session.bind.sync_engine

    def _before_cursor_execute(
        _conn, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        statements.append(str(statement))

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        res = await client.get("/api/dashboard/badges")
        assert res.status_code == 200
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)

    invoice_from = sum(
        1 for s in statements if "from invoices" in str(s).lower()
    )
    # Auth/RLS + status GROUP BY + route GROUP BY + payments fallback +
    # pending classification. Route queues used to be three extra COUNTs.
    assert 1 <= invoice_from <= 8, invoice_from
    assert 1 <= len(statements) <= 25, len(statements)


@pytest.mark.asyncio
async def test_setup_checklist_skips_item_queries_when_already_complete(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.tenant import tenant_setup_checklist_service as svc

    tenant = await db_session.get(Tenant, TESTING_TENANT_UUID)
    assert tenant is not None
    tenant.settings_json = {
        **(tenant.settings_json or {}),
        "setup_checklist_complete": True,
    }

    async def fail(*_args, **_kwargs):
        raise AssertionError("item queries must not run when checklist is complete")

    monkeypatch.setattr(svc, "_item_done", fail)
    state = await svc.build_setup_checklist_state(
        db_session,
        tenant=tenant,
        user_role="admin",
        is_support_session=False,
    )
    assert state.complete is True
    assert state.show is False
    assert state.items == []
    assert state.progress == 100
