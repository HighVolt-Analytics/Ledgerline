
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus


@pytest.mark.asyncio
async def test_list_empty(client: AsyncClient) -> None:
    res = await client.get("/api/invoices")
    assert res.status_code == 200
    body = res.json()
    assert body["error"] is None
    assert body["data"] == []


@pytest.mark.asyncio
async def test_get_invoice(client: AsyncClient, db_session: AsyncSession) -> None:
    inv = Invoice(tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        invoice_no="INV-1",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="a1",
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.get(f"/api/invoices/{inv.id}")
    assert res.status_code == 200
    assert res.json()["data"]["vendor"] == "Acme"


@pytest.mark.asyncio
async def test_get_invoice_pipeline(client: AsyncClient, db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.PENDING,
        currency="AUD",
        file_hash="pipeline-1",
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.get(f"/api/invoices/{inv.id}/pipeline")
    assert res.status_code == 200
    body = res.json()
    assert body["error"] is None
    assert "steps" in body["data"]
    assert isinstance(body["data"]["steps"], list)


@pytest.mark.asyncio
async def test_not_found(client: AsyncClient) -> None:
    res = await client.get("/api/invoices/99999")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_filter_status(client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add_all([
        Invoice(tenant_id=TESTING_TENANT_UUID, vendor="A", status=InvoiceStatus.PROCESSED, currency="AUD", file_hash="f1"),
        Invoice(tenant_id=TESTING_TENANT_UUID, vendor="B", status=InvoiceStatus.EXCEPTION, currency="AUD", file_hash="f2"),
    ])
    await db_session.flush()

    res = await client.get("/api/invoices?status=processed")
    assert res.status_code == 200
    assert len(res.json()["data"]) == 1


@pytest.mark.asyncio
async def test_patch_invoice_refreshes_vendor_evaluation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Saving vendor corrections re-runs evaluation so approve uses fresh routing."""
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Totally Unknown Supplier Ltd",
        route_target="Purchase Management",
        evaluation_status="auto_coded",
        vendor_confidence=0.9,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="patch-eval-1",
        total=Decimal("500.00"),
        due_date=date(2026, 7, 1),
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.patch(
        f"/api/invoices/{inv.id}",
        json={"vendor": "Another Unknown Vendor Pty Ltd"},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["vendor"] == "Another Unknown Vendor Pty Ltd"
    assert data["vendor_confidence"] == 0.0
    assert data["evaluation_status"] == "pending_vendor"


@pytest.mark.asyncio
async def test_patch_invoice_in_review_queue(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor=None,
        invoice_no=None,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="patch1",
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.patch(
        f"/api/invoices/{inv.id}",
        json={
            "vendor": "Fixed Vendor Pty Ltd",
            "invoice_no": "INV-99",
            "total": "1100.00",
            "line_items": [
                {"description": "Consulting", "qty": "1", "unit_price": "1000", "amount": "1000"}
            ],
        },
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["vendor"] == "Fixed Vendor Pty Ltd"
    assert data["invoice_no"] == "INV-99"
    assert len(data["line_items"]) == 1
    assert data["line_items"][0]["description"] == "Consulting"


@pytest.mark.asyncio
async def test_patch_invoice_persists_line_gl_accounts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        invoice_no="INV-GL",
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="patch-gl-1",
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.patch(
        f"/api/invoices/{inv.id}",
        json={
            "line_items": [
                {
                    "description": "Hotel stay",
                    "qty": "1",
                    "unit_price": "200",
                    "amount": "200",
                    "parent_ledger": "Travel Expense",
                    "sub_ledger": "Hotel",
                    "gl_mapping_source": "manual",
                }
            ],
        },
    )
    assert res.status_code == 200
    line = res.json()["data"]["line_items"][0]
    assert line["parent_ledger"] == "Travel Expense"
    assert line["sub_ledger"] == "Hotel"
    assert line["effective_ledger"] == "Hotel"


@pytest.mark.asyncio
async def test_patch_invoice_rejects_processed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="patch2",
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.patch(f"/api/invoices/{inv.id}", json={"vendor": "New Name"})
    assert res.status_code == 400
