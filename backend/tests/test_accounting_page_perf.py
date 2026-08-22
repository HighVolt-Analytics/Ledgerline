"""Accounting (Ledger Link) first-paint regressions (perf/accounting-optimization)."""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry
from app.models.payment import Payment, PaymentStatus
from app.services.invoice.invoice_evaluation_service import ROUTE_EXPENSES
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


async def _add_processed_invoice(
    db_session: AsyncSession,
    *,
    vendor: str,
    invoice_no: str,
    invoice_date: date,
    total: Decimal,
    currency: str,
    route_target: str,
    file_hash: str,
) -> Invoice:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor=vendor,
        invoice_no=invoice_no,
        invoice_date=invoice_date,
        total=total,
        currency=currency,
        status=InvoiceStatus.PROCESSED,
        route_target=route_target,
        file_hash=file_hash,
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        JournalEntry(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            date=invoice_date,
            account_code="6100",
            account_name="Office Expenses",
            debit=total,
            credit=Decimal("0"),
            entry_type=EntryType.DEBIT,
        )
    )
    db_session.add(
        JournalEntry(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            date=invoice_date,
            account_code="2000",
            account_name="Accounts Payable",
            debit=Decimal("0"),
            credit=total,
            entry_type=EntryType.CREDIT,
        )
    )
    await db_session.flush()
    return inv


@pytest.mark.asyncio
async def test_ledger_overview_slice_skips_exports_and_posting_blobs(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv = await _add_processed_invoice(
        db_session,
        vendor="Acme",
        invoice_no="LL-OV-1",
        invoice_date=date(2026, 5, 1),
        total=Decimal("110.00"),
        currency="AUD",
        route_target=ROUTE_EXPENSES,
        file_hash="ll-ov-1",
    )
    db_session.add(
        Payment(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            vendor="Acme",
            amount=Decimal("110.00"),
            currency="AUD",
            status=PaymentStatus.PAID,
        )
    )
    await db_session.flush()

    statements, stop = _capture_sql(db_session)
    try:
        res = await client.get("/api/ledger-link?fields=overview")
    finally:
        stop()

    assert res.status_code == 200
    data = res.json()["data"]
    assert data["exports"]["invoices"] == []
    assert data["exports"]["bills"] == []
    assert data["exports"]["payments"] == []
    overview = data["overview"]
    assert overview["document_count"] == 1
    assert Decimal(str(overview["sum_dr"])) == Decimal("110.00")
    assert overview["balanced"] is True
    assert overview["by_date"][0]["count"] == 1
    assert overview["by_date"][0]["invoices"] == []

    sql = " ".join(statements).lower()
    assert "payments" not in sql
    assert "audit_logs" not in sql


@pytest.mark.asyncio
async def test_ledger_overview_kpis_are_not_truncated_to_shown_days(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _add_processed_invoice(
        db_session,
        vendor="Old Co",
        invoice_no="LL-OLD",
        invoice_date=date(2024, 1, 2),
        total=Decimal("40.00"),
        currency="AUD",
        route_target=ROUTE_EXPENSES,
        file_hash="ll-old",
    )
    await _add_processed_invoice(
        db_session,
        vendor="New Co",
        invoice_no="LL-NEW",
        invoice_date=date(2026, 5, 1),
        total=Decimal("60.00"),
        currency="AUD",
        route_target=ROUTE_EXPENSES,
        file_hash="ll-new",
    )

    res = await client.get("/api/ledger-link?fields=overview")
    assert res.status_code == 200
    overview = res.json()["data"]["overview"]
    assert overview["document_count"] == 2
    assert overview["total_day_count"] == 2
    assert Decimal(str(overview["sum_dr"])) == Decimal("100.00")
    assert Decimal(str(overview["sum_cr"])) == Decimal("100.00")


@pytest.mark.asyncio
async def test_ledger_day_expand_returns_postings(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _add_processed_invoice(
        db_session,
        vendor="Acme",
        invoice_no="LL-DAY-1",
        invoice_date=date(2026, 5, 1),
        total=Decimal("110.00"),
        currency="AUD",
        route_target=ROUTE_EXPENSES,
        file_hash="ll-day-1",
    )

    res = await client.get("/api/ledger-link/days/2026-05-01")
    assert res.status_code == 200
    day = res.json()["data"]
    assert day["count"] == 1
    assert day["invoices"][0]["id"]
    assert len(day["invoices"][0]["postings"]) == 2


@pytest.mark.asyncio
async def test_ledger_exports_meta_stays_accurate_when_capped(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv = await _add_processed_invoice(
        db_session,
        vendor="Acme",
        invoice_no="LL-EX-1",
        invoice_date=date(2026, 5, 1),
        total=Decimal("110.00"),
        currency="AUD",
        route_target=ROUTE_EXPENSES,
        file_hash="ll-ex-1",
    )
    db_session.add(
        Payment(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            vendor="Acme",
            amount=Decimal("25.00"),
            currency="AUD",
            status=PaymentStatus.QUEUE,
        )
    )
    await db_session.flush()

    res = await client.get("/api/ledger-link/exports?limit=50")
    assert res.status_code == 200
    data = res.json()["data"]
    assert any(row["doc"] == "LL-EX-1" for row in data["bills"])
    assert data["group_meta"]["bills"]["count"] == 1
    assert data["group_meta"]["bills"]["totals_by_currency"]["AUD"] == 110.0
    assert data["group_meta"]["payments"]["count"] == 1
