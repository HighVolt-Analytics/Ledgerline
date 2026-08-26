"""Rule Book workspace first-paint regressions (perf/rule-book-optimization)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

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
async def test_rule_book_editor_slice_skips_masters(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        VendorMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="vm-rulebook-1",
            name="Rule Book Vendor",
            aliases=[],
            abn="51824753556",
        )
    )
    await db_session.flush()

    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/rule-book/config?fields=editor")
    finally:
        stop()

    assert res.status_code == 200
    body = res.json()["data"]
    assert body.get("vendor_masters") == []
    assert body.get("employee_masters") == []
    assert body.get("email_capture_rules")
    assert body.get("document_types")
    sql = " ".join(statements).lower()
    assert "vendor_masters" not in sql
    assert "employee_masters" not in sql
    assert "audit_logs" not in sql


@pytest.mark.asyncio
async def test_rule_book_ingest_stats_slice_uses_audit_group_by(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/rule-book/config?fields=ingest_stats")
    finally:
        stop()

    assert res.status_code == 200
    body = res.json()["data"]
    assert "email_capture_ingest_stats" in body
    sql = " ".join(statements).lower()
    assert "audit_logs" in sql
    assert "group by" in sql


@pytest.mark.asyncio
async def test_rule_book_full_config_skips_ingest_stats_audit_scan(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/rule-book/config")
    finally:
        stop()

    assert res.status_code == 200
    sql = " ".join(statements).lower()
    assert "audit_logs" not in sql
