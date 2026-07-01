"""Pending vendor queue visibility in Rule Book."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.pending_vendor import PendingVendor
from app.services.invoice_evaluation_service import EVAL_PENDING_VENDOR, apply_invoice_evaluation
from app.services.master_data_service import list_pending_vendors
from app.services.vendor_hold_service import apply_vendor_hold_if_needed
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_apply_invoice_evaluation_enqueues_pending_vendor(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Mystery Supplies Pty Ltd",
        invoice_no="MYS-001",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
        file_hash="pending-queue-eval",
        document_type_code="DT-01",
        document_type_confidence=0.9,
        route_target="Purchase Management",
        vendor_confidence=35.0,
    )
    db_session.add(inv)
    await db_session.flush()
    loaded = (
        await db_session.execute(
            select(Invoice)
            .where(Invoice.id == inv.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one()

    await apply_invoice_evaluation(db_session, loaded)
    assert loaded.evaluation_status == EVAL_PENDING_VENDOR

    queue = await list_pending_vendors(db_session, TESTING_TENANT_UUID)
    assert any(row.detected_name == "Mystery Supplies Pty Ltd" for row in queue)


@pytest.mark.asyncio
async def test_vendor_hold_enqueues_missing_pending_vendor_row(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Unknown Supplier Pty Ltd",
        vendor_confidence=35.0,
        status=InvoiceStatus.VALIDATING,
        evaluation_status=EVAL_PENDING_VENDOR,
        currency="AUD",
        file_hash="pending-queue-hold",
        document_type_code="DT-01",
        document_type_confidence=0.9,
        route_target="Purchase Management",
    )
    db_session.add(inv)
    await db_session.flush()

    held = await apply_vendor_hold_if_needed(db_session, inv)
    assert held
    assert inv.status == InvoiceStatus.EXCEPTION

    rows = (
        await db_session.execute(
            select(PendingVendor).where(
                PendingVendor.tenant_id == TESTING_TENANT_UUID,
                PendingVendor.status == "pending",
            )
        )
    ).scalars().all()
    assert any(row.detected_name == "Unknown Supplier Pty Ltd" for row in rows)

    api_rows = await list_pending_vendors(db_session, TESTING_TENANT_UUID)
    assert any(row.detected_name == "Unknown Supplier Pty Ltd" for row in api_rows)
