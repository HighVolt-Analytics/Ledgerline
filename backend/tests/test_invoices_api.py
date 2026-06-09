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
    inv = Invoice(org_id=1,
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
async def test_not_found(client: AsyncClient) -> None:
    res = await client.get("/api/invoices/99999")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_filter_status(client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add_all([
        Invoice(org_id=1, vendor="A", status=InvoiceStatus.PROCESSED, currency="AUD", file_hash="f1"),
        Invoice(org_id=1, vendor="B", status=InvoiceStatus.EXCEPTION, currency="AUD", file_hash="f2"),
    ])
    await db_session.flush()

    res = await client.get("/api/invoices?status=processed")
    assert res.status_code == 200
    assert len(res.json()["data"]) == 1


@pytest.mark.asyncio
async def test_patch_invoice_in_review_queue(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv = Invoice(
        org_id=1,
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
async def test_patch_invoice_rejects_processed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv = Invoice(
        org_id=1,
        vendor="Acme",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="patch2",
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.patch(f"/api/invoices/{inv.id}", json={"vendor": "New Name"})
    assert res.status_code == 400
