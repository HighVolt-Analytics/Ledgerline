"""Approval must preserve user-corrected invoice fields."""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.approval_service import approve_invoice_for_reprocess


@pytest.mark.asyncio
async def test_approve_preserves_corrected_fields(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    inv = Invoice(
        tenant_id=1,
        vendor="ram",
        total=Decimal("110.00"),
        due_date=date(2026, 7, 1),
        billing_address="LedgerLine Test Tenant",
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="approve-preserve-1",
        raw_file_path="/tmp/invoice.pdf",
    )
    db_session.add(inv)
    await db_session.flush()

    monkeypatch.setattr(
        "app.services.approval_service.stored_file_available",
        lambda *args, **kwargs: True,
    )

    await approve_invoice_for_reprocess(db_session, inv)

    assert inv.status == InvoiceStatus.PENDING
    assert inv.vendor == "ram"
    assert inv.total == Decimal("110.00")
    assert inv.due_date == date(2026, 7, 1)
    assert inv.billing_address == "LedgerLine Test Tenant"


@pytest.mark.asyncio
async def test_approve_requires_vendor_total_due_date(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    inv = Invoice(
        tenant_id=1,
        vendor=None,
        total=None,
        due_date=None,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="approve-missing-1",
        raw_file_path="/tmp/invoice.pdf",
    )
    db_session.add(inv)
    await db_session.flush()

    monkeypatch.setattr(
        "app.services.approval_service.stored_file_available",
        lambda *args, **kwargs: True,
    )

    with pytest.raises(ValueError, match="missing required field"):
        await approve_invoice_for_reprocess(db_session, inv)


@pytest.mark.asyncio
async def test_patch_billing_address(client: AsyncClient, db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=1,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="patch-billing-1",
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.patch(
        f"/api/invoices/{inv.id}",
        json={"billing_address": "LedgerLine Test Tenant", "vendor": "ram", "total": "110.00", "due_date": "2026-07-01"},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["billing_address"] == "LedgerLine Test Tenant"
    assert data["vendor"] == "ram"
