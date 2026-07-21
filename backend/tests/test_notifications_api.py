from datetime import datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant_billing import TenantBilling
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_notifications_empty(client: AsyncClient) -> None:
    res = await client.get("/api/notifications")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["items"] == []
    assert data["unread_count"] == 0


@pytest.mark.asyncio
async def test_notifications_pipeline_error(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Error Vendor",
        document_ref="INV-ERR-1",
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="notif-err-1",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        AuditLog(
            tenant_id=TESTING_TENANT_UUID,
            event="pipeline_error",
            invoice_id=inv.id,
            detail={"error": "OCR failed", "document_ref": "INV-ERR-1"},
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    res = await client.get("/api/notifications")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["unread_count"] >= 1
    row = next(item for item in data["items"] if item["event"] == "pipeline_error")
    assert row["severity"] == "error"
    assert row["href"] == f"/approvals?invoice={inv.id}"
    assert row["is_unread"] is True


@pytest.mark.asyncio
async def test_notifications_tenant_only_integration_error(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        AuditLog(
            tenant_id=TESTING_TENANT_UUID,
            event="accounting_integration_error",
            invoice_id=None,
            detail={"provider": "xero", "reason": "OAuth failed"},
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    res = await client.get("/api/notifications")
    assert res.status_code == 200
    data = res.json()["data"]
    row = next(
        item for item in data["items"] if item["event"] == "accounting_integration_error"
    )
    assert row["audit_log_id"] is not None
    assert row["href"] == "/integrations"
    assert row["severity"] == "error"


@pytest.mark.asyncio
async def test_notifications_vendor_registration_hold(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Unknown Supplier",
        document_ref="INV-HOLD-1",
        route_target="Purchase Management",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="pending_vendor",
        currency="AUD",
        file_hash="notif-vhold-1",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        AuditLog(
            tenant_id=TESTING_TENANT_UUID,
            event="vendor_registration_hold",
            invoice_id=inv.id,
            detail={
                "vendor": "Unknown Supplier",
                "vendor_confidence": 12.0,
                "reason": "pending_vendor_registration",
            },
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    res = await client.get("/api/notifications")
    assert res.status_code == 200
    data = res.json()["data"]
    row = next(item for item in data["items"] if item["event"] == "vendor_registration_hold")
    assert row["severity"] == "action"
    assert row["href"] == f"/approvals?invoice={inv.id}"
    assert "Unknown Supplier" in row["title"]


@pytest.mark.asyncio
async def test_notifications_customer_registration_hold(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Unknown Buyer",
        document_ref="SO-HOLD-1",
        route_target="Sales Management",
        status=InvoiceStatus.EXCEPTION,
        evaluation_status="pending_vendor",
        currency="AUD",
        file_hash="notif-chold-1",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        AuditLog(
            tenant_id=TESTING_TENANT_UUID,
            event="customer_registration_hold",
            invoice_id=inv.id,
            detail={
                "customer": "Unknown Buyer",
                "customer_confidence": 8.0,
                "reason": "pending_customer_registration",
            },
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    res = await client.get("/api/notifications")
    assert res.status_code == 200
    data = res.json()["data"]
    row = next(item for item in data["items"] if item["event"] == "customer_registration_hold")
    assert row["severity"] == "action"
    assert row["href"] == f"/approvals?invoice={inv.id}"
    assert "Unknown Buyer" in row["title"]


@pytest.mark.asyncio
async def test_notifications_mark_read(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        AuditLog(
            tenant_id=TESTING_TENANT_UUID,
            event="invoice_processed",
            detail={"vendor": "Acme"},
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    before = (await client.get("/api/notifications")).json()["data"]
    assert before["unread_count"] >= 1

    mark = await client.post("/api/notifications/mark-read")
    assert mark.status_code == 200
    assert mark.json()["data"]["unread_count"] == 0

    after = (await client.get("/api/notifications")).json()["data"]
    assert after["unread_count"] == 0
    assert all(not item["is_unread"] for item in after["items"])


@pytest.mark.asyncio
async def test_notifications_low_credits(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    billing = await db_session.get(TenantBilling, TESTING_TENANT_UUID)
    assert billing is not None
    billing.credit_balance = 50
    billing.updated_at = datetime.now(timezone.utc)
    await db_session.flush()

    res = await client.get("/api/notifications")
    assert res.status_code == 200
    data = res.json()["data"]
    row = next(item for item in data["items"] if item["id"] == "system:low_credits")
    assert row["event"] == "low_credits"
    assert row["severity"] == "action"
    assert row["href"] == "/billing"
    assert row["is_unread"] is True

    await client.post("/api/notifications/mark-read")
    after = (await client.get("/api/notifications")).json()["data"]
    low = next(item for item in after["items"] if item["id"] == "system:low_credits")
    assert low["is_unread"] is False


@pytest.mark.asyncio
async def test_notifications_duplicate_skipped_uses_document_ref(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    original = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Skylift",
        invoice_no="250970286",
        document_ref="DOC-40",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="notif-dup-orig",
    )
    shadow = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Skylift",
        invoice_no="250970286",
        document_ref="DOC-86",
        status=InvoiceStatus.DUPLICATE_SKIPPED,
        currency="AUD",
        file_hash=None,
    )
    db_session.add_all([original, shadow])
    await db_session.flush()
    db_session.add(
        AuditLog(
            tenant_id=TESTING_TENANT_UUID,
            event="duplicate_skipped",
            invoice_id=shadow.id,
            detail={
                "original_invoice_id": original.id,
                "filename": "skylift.pdf",
                "source": "upload",
                "invoice_no": "250970286",
            },
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    res = await client.get("/api/notifications")
    assert res.status_code == 200
    row = next(
        item for item in res.json()["data"]["items"] if item["event"] == "duplicate_skipped"
    )
    assert "DOC-86" in row["title"]
    assert "matches DOC-40" in row["summary"]
    assert f"matches invoice {original.id}" not in row["summary"]
    assert str(original.id) not in row["summary"]


@pytest.mark.asyncio
async def test_notifications_invoice_processed_info(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Processed Vendor",
        total=Decimal("500.00"),
        document_ref="INV-OK-1",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="notif-ok-1",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        AuditLog(
            tenant_id=TESTING_TENANT_UUID,
            event="invoice_processed",
            invoice_id=inv.id,
            detail={"vendor": "Processed Vendor", "amount": "500.00"},
            created_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    res = await client.get("/api/notifications")
    row = next(item for item in res.json()["data"]["items"] if item["event"] == "invoice_processed")
    assert row["severity"] == "info"
    assert row["href"] == f"/vault?invoice={inv.id}"
