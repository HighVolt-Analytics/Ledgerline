
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Reports analytics API tests."""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus


@pytest.mark.asyncio
async def test_reports_analytics_empty(client: AsyncClient) -> None:
    res = await client.get("/api/reports/analytics")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["document_count"] == 0
    assert data["period_has_data"] is False
    assert data["by_gl_account"] == []
    assert data["top_vendors"] == []


@pytest.mark.asyncio
async def test_reports_analytics_processed_invoices(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="AWS",
                invoice_no="INV-001",
                invoice_date=date(2026, 5, 2),
                account_name="Cloud Hosting Expense",
                subtotal=Decimal("100.00"),
                gst=Decimal("10.00"),
                total=Decimal("110.00"),
                currency="AUD",
                status=InvoiceStatus.PROCESSED,
                file_hash="rep1",
            ),
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Atlassian",
                invoice_date=date(2026, 5, 4),
                account_name="Software Subscription Expense",
                subtotal=Decimal("200.00"),
                gst=Decimal("20.00"),
                total=Decimal("220.00"),
                currency="AUD",
                status=InvoiceStatus.PROCESSED,
                file_hash="rep2",
            ),
            Invoice(
                tenant_id=TESTING_TENANT_UUID,
                vendor="Pending Co",
                invoice_date=date(2026, 5, 6),
                total=Decimal("999.00"),
                currency="AUD",
                status=InvoiceStatus.PENDING,
                file_hash="rep3",
            ),
        ]
    )
    await db_session.flush()

    res = await client.get("/api/reports/analytics?month=2026-05")
    assert res.status_code == 200
    data = res.json()["data"]
    # Pending + processed are downloadable; rejected/duplicate_skipped stay excluded.
    assert data["document_count"] == 3
    assert data["period_has_data"] is True
    assert Decimal(data["net_spend"]) == Decimal("300.00")
    assert Decimal(data["gross_spend"]) == Decimal("1329.00")
    assert len(data["by_gl_account"]) == 3
    assert data["top_vendors"][0]["vendor"] == "Pending Co"


@pytest.mark.asyncio
async def test_reports_documents_date_range(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        Invoice(
            tenant_id=TESTING_TENANT_UUID,
            vendor="Telstra",
            document_ref="BILL-040",
            invoice_no="BILL-040",
            invoice_date=date(2026, 4, 14),
            account_name="Telephone & Internet",
            subtotal=Decimal("80.00"),
            gst=Decimal("8.00"),
            total=Decimal("88.00"),
            currency="AUD",
            status=InvoiceStatus.PROCESSED,
            file_hash="rep4",
        )
    )
    await db_session.flush()

    res = await client.get(
        "/api/reports/documents",
        params={"date_from": "2026-04-01", "date_to": "2026-04-30"},
    )
    assert res.status_code == 200
    rows = res.json()["data"]
    assert len(rows) == 1
    assert rows[0]["document_ref"] == "BILL-040"
    assert rows[0]["account"] == "Telephone & Internet"
    assert rows[0]["vendor"] == "Telstra"
