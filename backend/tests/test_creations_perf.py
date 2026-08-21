"""Creations workspace first-paint regressions (perf/creations-optimization)."""

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
async def test_rule_book_vendor_detection_slice_skips_masters(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        VendorMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="vm-creations-1",
            name="Creations Vendor",
            aliases=[],
            abn="51824753556",
        )
    )
    await db_session.flush()

    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/rule-book/config?fields=vendor_detection")
    finally:
        stop()

    assert res.status_code == 200
    body = res.json()["data"]
    assert set(body.keys()) == {"vendor_detection_config"}
    assert "threshold" in body["vendor_detection_config"]
    sql = " ".join(statements).lower()
    assert "vendor_masters" not in sql
    assert "employee_masters" not in sql


@pytest.mark.asyncio
async def test_rule_book_vendor_detection_put_preserves_hold_and_types(
    client: AsyncClient,
) -> None:
    full = await client.get("/api/rule-book/config")
    assert full.status_code == 200
    original = full.json()["data"]
    hold = original["vendor_detection_config"].get("expense_vendor_hold_above")
    type_count = len(original.get("document_types") or [])

    res = await client.put(
        "/api/rule-book/config/vendor-detection",
        json={
            "vendor_detection_config": {
                "weights": original["vendor_detection_config"]["weights"],
                "threshold": 81,
            }
        },
    )
    assert res.status_code == 200
    assert res.json()["data"]["vendor_detection_config"]["threshold"] == 81

    after = (await client.get("/api/rule-book/config")).json()["data"]
    assert after["vendor_detection_config"]["threshold"] == 81
    assert after["vendor_detection_config"].get("expense_vendor_hold_above") == hold
    assert len(after.get("document_types") or []) == type_count


@pytest.mark.asyncio
async def test_pending_vendors_empty_skips_vendor_master_hydration(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Unrelated",
            total=Decimal("10.00"),
            status=InvoiceStatus.PROCESSED,
            currency="AUD",
            file_hash="creations-pending-empty",
        )
    )
    await db_session.flush()

    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/pending-vendors")
    finally:
        stop()

    assert res.status_code == 200
    assert res.json()["data"] == []
    sql = " ".join(statements).lower()
    assert "vendor_masters" not in sql


@pytest.mark.asyncio
async def test_vendor_masters_list_skips_empty_import_counts_when_rows_exist(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        VendorMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="vm-creations-list",
            name="Listed Vendor",
            aliases=[],
            abn="",
        )
    )
    await db_session.flush()

    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/vendor-masters")
    finally:
        stop()

    assert res.status_code == 200
    assert any(row["name"] == "Listed Vendor" for row in res.json()["data"])
    count_sql = [
        s
        for s in statements
        if "count(" in s.lower() and "vendor_masters" in s.lower()
    ]
    assert count_sql == []


@pytest.mark.asyncio
async def test_pending_customers_empty_skips_customer_master_hydration(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/pending-customers")
    finally:
        stop()

    assert res.status_code == 200
    assert res.json()["data"] == []
    sql = " ".join(statements).lower()
    assert "customer_masters" not in sql
