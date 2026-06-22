from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus


@pytest.mark.asyncio
async def test_dashboard_badges_empty(client: AsyncClient) -> None:
    res = await client.get("/api/dashboard/badges")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["inbox_count"] == 0
    assert data["pending_approval"] == 0
    assert data["team_expenses_count"] == 0
    assert data["payments_queue_count"] == 0
    assert "integrations_connected" in data


@pytest.mark.asyncio
async def test_dashboard_stats_empty(client: AsyncClient) -> None:
    res = await client.get("/api/dashboard/stats")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["total_invoices"] == 0
    assert data["synced_percent"] == 0
    assert data["pending_approval"] == 0
    assert data["inbox_count"] == 0
    assert data["distinct_vendors"] == 0
    assert data["docs_via_email"] == 0
    assert data["docs_via_upload"] == 0


@pytest.mark.asyncio
async def test_dashboard_overview(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv = Invoice(tenant_id=1,
        vendor="Acme Corp",
        total=Decimal("1000.00"),
        due_date=date.today() + timedelta(days=5),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="dash1",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        AuditLog(
            event="invoice_processed",
            invoice_id=inv.id,
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    res = await client.get("/api/dashboard/overview?activity_limit=5")
    assert res.status_code == 200
    body = res.json()["data"]
    assert body["stats"]["total_invoices"] == 1
    assert body["stats"]["processed"] == 1
    assert body["stats"]["distinct_vendors"] == 1
    assert body["stats"]["docs_via_upload"] == 1
    assert body["stats"]["total_value_aud"] == "1000.00"
    assert len(body["activity"]) >= 1
    assert body["top_vendors"][0]["vendor"] == "Acme Corp"
    assert len(body["cash_forecast"]) == 6
    seven_day = next(b for b in body["cash_forecast"] if b["label"] == "7 days")
    assert Decimal(seven_day["amount"]) == Decimal("1000.00")
    assert len(body["invoice_volume_sparkline"]) >= 1
    assert "period" in body
    assert "mailbox_breakdown" in body
    assert "anomalies" in body
    assert "kpi_trends" in body
    assert "kpi_sparklines" in body
    assert len(body["kpi_sparklines"]["docs_via_email"]) == 7
    assert body["period_has_data"] is True
    assert body["stats"]["base_currency"] == "AUD"
    assert "total_value" in body["stats"]


@pytest.mark.asyncio
async def test_dashboard_activity_includes_duplicate(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    original = Invoice(
        tenant_id=1,
        vendor="Dup Vendor",
        invoice_no="INV-DUP-1",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="dash-dup-original",
    )
    shadow = Invoice(
        tenant_id=1,
        vendor="Dup Vendor",
        invoice_no="INV-DUP-1",
        status=InvoiceStatus.DUPLICATE_SKIPPED,
        currency="AUD",
        file_hash=None,
    )
    db_session.add_all([original, shadow])
    await db_session.flush()
    db_session.add(
        AuditLog(
            event="duplicate_skipped",
            invoice_id=shadow.id,
            detail={
                "original_invoice_id": original.id,
                "filename": "invoice.pdf",
                "source": "email",
            },
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    res = await client.get("/api/dashboard/overview?activity_limit=10")
    assert res.status_code == 200
    activity = res.json()["data"]["activity"]
    dup_rows = [row for row in activity if row["event"] == "duplicate_skipped"]
    assert len(dup_rows) >= 1
    assert dup_rows[0]["summary"] is not None
    assert "Duplicate file skipped" in dup_rows[0]["summary"]


@pytest.mark.asyncio
async def test_pending_approval_count(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        Invoice(tenant_id=1,
            vendor="X",
            status=InvoiceStatus.EXCEPTION,
            currency="AUD",
            file_hash="ex1",
        )
    )
    await db_session.flush()

    res = await client.get("/api/dashboard/stats")
    assert res.json()["data"]["pending_approval"] == 1
    assert res.json()["data"]["exceptions"] == 1


@pytest.mark.asyncio
async def test_total_value_counts_processed_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Booked KPIs exclude exception, rejected, and duplicate invoices."""
    db_session.add_all(
        [
            Invoice(
                tenant_id=1,
                vendor="Booked Co",
                total=Decimal("1000.00"),
                status=InvoiceStatus.PROCESSED,
                currency="AUD",
                file_hash="dash-booked",
            ),
            Invoice(
                tenant_id=1,
                vendor="Exception Co",
                total=Decimal("500.00"),
                status=InvoiceStatus.EXCEPTION,
                currency="AUD",
                file_hash="dash-exc",
            ),
            Invoice(
                tenant_id=1,
                vendor="Rejected Co",
                total=Decimal("250.00"),
                status=InvoiceStatus.REJECTED,
                currency="AUD",
                file_hash="dash-rej",
            ),
            Invoice(
                tenant_id=1,
                vendor="Dupe Co",
                total=Decimal("100.00"),
                status=InvoiceStatus.DUPLICATE_SKIPPED,
                currency="AUD",
                file_hash="dash-dupe",
            ),
        ]
    )
    await db_session.flush()

    res = await client.get("/api/dashboard/stats")
    data = res.json()["data"]
    assert Decimal(data["total_value_aud"]) == Decimal("1000.00")
    assert data["processed"] == 1
    assert data["rejected"] == 1
    assert data["distinct_vendors"] == 1

    overview = await client.get("/api/dashboard/overview")
    body = overview.json()["data"]
    assert len(body["top_vendors"]) == 1
    assert body["top_vendors"][0]["vendor"] == "Booked Co"
    assert Decimal(body["top_vendors"][0]["amount"]) == Decimal("1000.00")
    forecast_total = sum(
        Decimal(b["amount"]) for b in body["cash_forecast"]
    )
    assert forecast_total == Decimal("0")


@pytest.mark.asyncio
async def test_reject_processed_updates_dashboard_value(
    client: AsyncClient, db_session: AsyncSession, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")
    get_settings.cache_clear()

    vault_path = upload_dir / "invoice" / "HvOrg" / "Spend Co" / "2026" / "May"
    vault_path.mkdir(parents=True)
    pdf = vault_path / "INV-010_2026-05-04_id1.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    inv = Invoice(
        tenant_id=1,
        vendor="Spend Co",
        invoice_no="INV-010",
        invoice_date=date(2026, 5, 4),
        due_date=date.today() + timedelta(days=5),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="dash-reject-flow",
        raw_file_path=str(pdf),
        total=Decimal("1500.00"),
    )
    db_session.add(inv)
    await db_session.flush()

    before = (await client.get("/api/dashboard/stats")).json()["data"]
    assert Decimal(before["total_value_aud"]) == Decimal("1500.00")
    assert before["processed"] == 1
    assert before["rejected"] == 0
    assert before["synced_percent"] == 100

    reject_res = await client.post(f"/api/approvals/{inv.id}/reject")
    assert reject_res.status_code == 200

    after = (await client.get("/api/dashboard/stats")).json()["data"]
    assert Decimal(after["total_value_aud"]) == Decimal("0")
    assert after["processed"] == 0
    assert after["rejected"] == 1
    assert after["synced_percent"] == 0

    overview = (await client.get("/api/dashboard/overview")).json()["data"]
    assert overview["top_vendors"] == []
    seven_day = next(b for b in overview["cash_forecast"] if b["label"] == "7 days")
    assert Decimal(seven_day["amount"]) == Decimal("0")


@pytest.mark.asyncio
async def test_nav_badges_team_expenses_and_payments(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            Invoice(
                tenant_id=1,
                vendor="Team Vendor",
                status=InvoiceStatus.VALIDATING,
                route_target="Team Expenses",
                currency="AUD",
                file_hash="badge-team",
            ),
            Invoice(
                tenant_id=1,
                vendor="Payable Co",
                status=InvoiceStatus.PROCESSED,
                due_date=date.today() + timedelta(days=3),
                total=Decimal("500.00"),
                currency="AUD",
                file_hash="badge-pay",
            ),
        ]
    )
    await db_session.flush()

    data = (await client.get("/api/dashboard/badges")).json()["data"]
    assert data["team_expenses_count"] == 1
    assert data["payments_queue_count"] == 1


@pytest.mark.asyncio
async def test_docs_via_upload_counts_non_email_sources(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            Invoice(
                tenant_id=1,
                vendor="Email Co",
                status=InvoiceStatus.PENDING,
                email_sender="vendor@example.com",
                currency="AUD",
                file_hash="dash-email",
            ),
            Invoice(
                tenant_id=1,
                vendor="Upload Co",
                status=InvoiceStatus.PENDING,
                currency="AUD",
                file_hash="dash-upload",
            ),
        ]
    )
    await db_session.flush()

    stats = (await client.get("/api/dashboard/stats")).json()["data"]
    assert stats["docs_via_email"] == 1
    assert stats["docs_via_upload"] == 1


@pytest.mark.asyncio
async def test_dashboard_anomalies_include_rule_book_routing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            Invoice(
                tenant_id=1,
                vendor="Unknown Supplier Pty Ltd",
                status=InvoiceStatus.MAPPING,
                route_target="Purchase Management",
                evaluation_status="pending_vendor",
                currency="AUD",
                file_hash="dash-pending-vendor",
            ),
            Invoice(
                tenant_id=1,
                vendor="Ambiguous Co",
                status=InvoiceStatus.VALIDATING,
                route_target="Team Expenses",
                evaluation_status="needs_review",
                currency="AUD",
                file_hash="dash-needs-review",
            ),
        ]
    )
    await db_session.flush()

    overview = (await client.get("/api/dashboard/overview")).json()["data"]
    tags = {row["tag"] for row in overview["anomalies"]}
    assert "Pending vendor" in tags
    assert "Needs review" in tags
