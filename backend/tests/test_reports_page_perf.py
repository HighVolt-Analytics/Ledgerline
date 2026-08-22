"""Reports first-paint regressions (perf/reports-optimization)."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.vendor_master import VendorMasterRecord
from app.schemas.master_data import EmployeeMasterCreate
from app.services.master_data.master_data_service import create_employee_master
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
async def test_reports_analytics_skips_ocr_blobs(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="AWS",
            invoice_no="INV-REP-1",
            invoice_date=date(2026, 5, 2),
            account_name="Cloud Hosting Expense",
            subtotal=Decimal("100.00"),
            gst=Decimal("10.00"),
            total=Decimal("110.00"),
            currency="AUD",
            status=InvoiceStatus.PROCESSED,
            file_hash=uuid4().hex,
            document_text="huge ocr blob should not be selected",
        )
    )
    await db_session.flush()

    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/reports/analytics?month=2026-05")
    finally:
        stop()

    assert res.status_code == 200
    data = res.json()["data"]
    assert data["document_count"] == 1
    sql = " ".join(statements).lower()
    assert "document_text" not in sql
    assert "approval_chain" not in sql
    assert "extracted_fields" not in sql


@pytest.mark.asyncio
async def test_ap_balances_skip_vendor_master_hydration(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        VendorMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="vm-reports-ap",
            name="Reports Vendor",
            aliases=[],
            abn="51824753556",
        )
    )
    await db_session.flush()

    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/reports/subledger/ap-balances")
    finally:
        stop()

    assert res.status_code == 200
    sql = " ".join(statements).lower()
    assert "vendor_masters" not in sql
    assert "employee_masters" not in sql


@pytest.mark.asyncio
async def test_advance_settlement_batches_pending_claims(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    for index in range(3):
        await create_employee_master(
            db_session,
            TESTING_TENANT_UUID,
            EmployeeMasterCreate(
                master_id=f"EMP-REP-{index}",
                name=f"Reporter {index}",
                email=f"reporter{index}@example.com",
            ),
        )
        db_session.add(
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor=f"Claim {index}",
                status=InvoiceStatus.PENDING,
                currency="AUD",
                total=Decimal("20.00"),
                route_target="Team Expenses",
                team_expense_kind="expense_claim",
                email_sender=f"reporter{index}@example.com",
                file_hash=uuid4().hex,
            )
        )
    await db_session.flush()

    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/reports/team-expenses/advance-settlement")
    finally:
        stop()

    assert res.status_code == 200
    invoice_scans = [
        sql
        for sql in statements
        if "from invoices" in sql.lower() and "route_target" in sql.lower()
    ]
    assert len(invoice_scans) == 1
