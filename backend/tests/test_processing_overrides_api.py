"""PATCH /api/invoices processing_overrides."""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_patch_processing_overrides(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="override-patch-1",
        total=Decimal("100.00"),
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.patch(
        f"/api/invoices/{inv.id}",
        json={"processing_overrides": {"skip_steps": ["validation", "playbook"]}},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["processing_overrides"]["skip_steps"] == ["playbook", "validation"]

    events = (
        await db_session.execute(
            select(AuditLog.event).where(AuditLog.invoice_id == inv.id)
        )
    ).scalars().all()
    assert "processing_overrides_updated" in events


@pytest.mark.asyncio
async def test_patch_processing_overrides_rejects_unknown_step(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="override-patch-2",
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.patch(
        f"/api/invoices/{inv.id}",
        json={"processing_overrides": {"skip_steps": ["made_up_gate"]}},
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_patch_processing_overrides_null_clears(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="override-patch-clear-1",
        total=Decimal("100.00"),
        processing_overrides={"skip_steps": ["validation"]},
    )
    db_session.add(inv)
    await db_session.flush()

    res = await client.patch(
        f"/api/invoices/{inv.id}",
        json={"processing_overrides": None},
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["processing_overrides"]["skip_steps"] == []
