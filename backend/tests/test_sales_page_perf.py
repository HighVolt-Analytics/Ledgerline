"""Sales Management first-paint regressions (perf/sales-optimization)."""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.sales_order import SalesOrder
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
async def test_rule_book_sales_rules_slice_skips_masters(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        VendorMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="vm-so-page-1",
            name="Sales Vendor",
            aliases=[],
            abn="51824753556",
        )
    )
    await db_session.flush()

    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/rule-book/config?fields=sales_rules")
    finally:
        stop()

    assert res.status_code == 200
    body = res.json()["data"]
    assert set(body.keys()) == {"sales_rules"}
    assert isinstance(body["sales_rules"], list)
    sql = " ".join(statements).lower()
    assert "vendor_masters" not in sql
    assert "employee_masters" not in sql


@pytest.mark.asyncio
async def test_sales_register_list_skips_vendor_master_hydration(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        VendorMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="vm-so-list-1",
            name="Register Customer",
            aliases=[],
            abn="51824753556",
        )
    )
    so_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="so-list-doc-1",
        route_target="Sales Management",
        sales_document_type="so",
        so_reference="SO-LIST-1",
    )
    db_session.add(so_doc)
    await db_session.flush()
    db_session.add(
        SalesOrder(
            tenant_id=TESTING_TENANT_UUID,
            so_number="SO-LIST-1",
            customer="Harbour View",
            so_qty=Decimal("1"),
            so_unit_price=Decimal("10"),
            so_document_id=so_doc.id,
        )
    )
    await db_session.flush()

    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/sales")
    finally:
        stop()

    assert res.status_code == 200
    rows = res.json()["data"]
    assert any(row["so_number"] == "SO-LIST-1" for row in rows)
    sql = " ".join(statements).lower()
    assert "vendor_masters" not in sql
    assert "employee_masters" not in sql


@pytest.mark.asyncio
async def test_sales_two_way_skips_full_register_rebuild(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    so_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="so-tw-doc-1",
        route_target="Sales Management",
        sales_document_type="so",
        so_reference="SO-TW-1",
    )
    db_session.add(so_doc)
    await db_session.flush()
    db_session.add(
        SalesOrder(
            tenant_id=TESTING_TENANT_UUID,
            so_number="SO-TW-1",
            customer="Harbour View",
            so_qty=Decimal("1"),
            so_unit_price=Decimal("10"),
            so_document_id=so_doc.id,
        )
    )
    await db_session.flush()

    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/sales/two-way")
    finally:
        stop()

    assert res.status_code == 200
    body = res.json()["data"]
    assert body["register_rows"] == []
    assert isinstance(body["orphan_rows"], list)
    sql = " ".join(statements).lower()
    assert "sales_order_lines" not in sql
    assert "vendor_masters" not in sql


@pytest.mark.asyncio
async def test_sales_workspace_kpis_are_uncapped(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    awaiting = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Hold Co",
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="so-kpi-await-1",
        route_target="Sales Management",
        evaluation_status="awaiting_so",
        sales_document_type="invoice",
    )
    unlinked_so = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Hold Co",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="so-kpi-unlinked-1",
        route_target="Sales Management",
        sales_document_type="so",
        so_reference="SO-KPI-UNLINKED",
    )
    linked_inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Hold Co",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="so-kpi-linked-1",
        route_target="Sales Management",
        sales_document_type="invoice",
        so_reference="SO-KPI-LINKED",
    )
    db_session.add_all([awaiting, unlinked_so, linked_inv])
    await db_session.flush()
    db_session.add(
        SalesOrder(
            tenant_id=TESTING_TENANT_UUID,
            so_number="SO-KPI-LINKED",
            customer="Hold Co",
            so_qty=Decimal("1"),
            so_unit_price=Decimal("25"),
            invoice_id=linked_inv.id,
        )
    )
    await db_session.flush()

    res = await client.get("/api/sales/kpis")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["awaiting_so_count"] == 1
    assert body["needs_action_count"] == 2
