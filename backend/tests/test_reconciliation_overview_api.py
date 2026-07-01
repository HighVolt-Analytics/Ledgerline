
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Reconciliation overview API tests."""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry


@pytest.mark.asyncio
async def test_reconciliation_overview_empty(client: AsyncClient) -> None:
    res = await client.get("/api/reconciliation/overview")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["balanced"] is True
    assert Decimal(data["sum_dr"]) == 0
    assert data["by_date"] == []


@pytest.mark.asyncio
async def test_reconciliation_overview_processed_with_journals(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv_date = date(2026, 5, 2)
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Amazon Web Services",
        document_ref="DOC-1",
        invoice_no="AWS-AU-204815",
        invoice_date=inv_date,
        subtotal=Decimal("1000.00"),
        gst=Decimal("100.00"),
        total=Decimal("1100.00"),
        currency="AUD",
        status=InvoiceStatus.PROCESSED,
        file_hash="recon_ov1",
    )
    db_session.add(inv)
    await db_session.flush()
    for code, name, dr, cr, et in [
        ("6100", "Cloud Hosting Expense", Decimal("1000.00"), Decimal("0"), EntryType.DEBIT),
        ("1400", "GST Paid", Decimal("100.00"), Decimal("0"), EntryType.DEBIT),
        ("2000", "Accounts Payable", Decimal("0"), Decimal("1100.00"), EntryType.CREDIT),
    ]:
        db_session.add(
            JournalEntry(
                tenant_id=TESTING_TENANT_UUID,
                invoice_id=inv.id,
                date=inv_date,
                account_code=code,
                account_name=name,
                debit=dr,
                credit=cr,
                entry_type=et,
            )
        )
    await db_session.flush()

    pending = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Pending Co",
        invoice_date=date(2026, 5, 3),
        total=Decimal("500.00"),
        currency="AUD",
        status=InvoiceStatus.PENDING,
        file_hash="recon_ov2",
    )
    db_session.add(pending)
    await db_session.flush()

    res = await client.get("/api/reconciliation/overview")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["balanced"] is True
    assert Decimal(data["sum_dr"]) == Decimal("1100.00")
    assert Decimal(data["sum_cr"]) == Decimal("1100.00")
    assert len(data["by_date"]) == 1
    day = data["by_date"][0]
    assert day["date"] == "2026-05-02"
    assert day["count"] == 1
    assert day["invoices"][0]["id"] == "DOC-1"
    assert len(day["invoices"][0]["postings"]) == 3


@pytest.mark.asyncio
async def test_reconciliation_overview_excludes_other_org(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv_date = date(2026, 4, 10)
    inv = Invoice(
        tenant_id=PLATFORM_TENANT_UUID,
        vendor="Other Org",
        invoice_date=inv_date,
        total=Decimal("200.00"),
        currency="AUD",
        status=InvoiceStatus.PROCESSED,
        file_hash="recon_ov3",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        JournalEntry(
            invoice_id=inv.id,
            date=inv_date,
            account_code="6100",
            account_name="Expense",
            debit=Decimal("200.00"),
            credit=Decimal("0"),
            entry_type=EntryType.DEBIT,
        )
    )
    await db_session.flush()

    res = await client.get("/api/reconciliation/overview")
    assert res.status_code == 200
    assert res.json()["data"]["by_date"] == []
