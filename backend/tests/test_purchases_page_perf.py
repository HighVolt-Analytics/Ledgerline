"""Purchase Management first-paint regressions (perf/purchases-optimization)."""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.purchase_order import PurchaseOrder
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
async def test_rule_book_purchase_rules_slice_skips_masters(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        VendorMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="vm-po-page-1",
            name="Purchase Vendor",
            aliases=[],
            abn="51824753556",
        )
    )
    await db_session.flush()

    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/rule-book/config?fields=purchase_rules")
    finally:
        stop()

    assert res.status_code == 200
    body = res.json()["data"]
    assert set(body.keys()) == {"purchase_rules"}
    assert isinstance(body["purchase_rules"], list)
    sql = " ".join(statements).lower()
    assert "vendor_masters" not in sql
    assert "employee_masters" not in sql


@pytest.mark.asyncio
async def test_purchase_register_list_skips_vendor_master_hydration(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        VendorMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="vm-po-list-1",
            name="Register Vendor",
            aliases=[],
            abn="51824753556",
        )
    )
    po_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="po-list-doc-1",
        route_target="Purchase Management",
        purchase_document_type="po",
        po_reference="PO-LIST-1",
    )
    db_session.add(po_doc)
    await db_session.flush()
    db_session.add(
        PurchaseOrder(
            tenant_id=TESTING_TENANT_UUID,
            po_number="PO-LIST-1",
            vendor="Acme",
            po_qty=Decimal("1"),
            po_unit_price=Decimal("10"),
            po_document_id=po_doc.id,
        )
    )
    await db_session.flush()

    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/purchases")
    finally:
        stop()

    assert res.status_code == 200
    rows = res.json()["data"]
    assert any(row["po_number"] == "PO-LIST-1" for row in rows)
    sql = " ".join(statements).lower()
    assert "vendor_masters" not in sql
    assert "employee_masters" not in sql


@pytest.mark.asyncio
async def test_purchase_workspace_kpis_are_uncapped(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    awaiting = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Hold Co",
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="po-kpi-await-1",
        route_target="Purchase Management",
        evaluation_status="awaiting_po",
        purchase_document_type="invoice",
    )
    unlinked_po = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Hold Co",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="po-kpi-unlinked-1",
        route_target="Purchase Management",
        purchase_document_type="po",
        po_reference="PO-KPI-UNLINKED",
    )
    linked_inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Hold Co",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="po-kpi-linked-1",
        route_target="Purchase Management",
        purchase_document_type="invoice",
        po_reference="PO-KPI-LINKED",
    )
    db_session.add_all([awaiting, unlinked_po, linked_inv])
    await db_session.flush()
    db_session.add(
        PurchaseOrder(
            tenant_id=TESTING_TENANT_UUID,
            po_number="PO-KPI-LINKED",
            vendor="Hold Co",
            po_qty=Decimal("1"),
            po_unit_price=Decimal("25"),
            invoice_id=linked_inv.id,
        )
    )
    await db_session.flush()

    res = await client.get("/api/purchases/kpis")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["awaiting_po_count"] == 1
    assert body["needs_action_count"] == 2
