"""Pending customer queue visibility in Customer masters."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.pending_customer import PendingCustomer
from app.services.invoice.invoice_evaluation_service import EVAL_PENDING_VENDOR, apply_invoice_evaluation
from app.services.master_data.customer_master_service import list_pending_customers
from app.services.master_data.customer_hold_service import apply_customer_hold_if_needed
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_apply_invoice_evaluation_enqueues_pending_customer(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Mystery Buyer Pty Ltd",
        invoice_no="MB-001",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
        file_hash="pending-customer-queue-eval",
        document_type_code="DT-26",
        document_type_confidence=0.9,
        route_target="Sales Management",
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

    queue = await list_pending_customers(db_session, TESTING_TENANT_UUID)
    assert any(row.detected_name == "Mystery Buyer Pty Ltd" for row in queue)


@pytest.mark.asyncio
async def test_customer_hold_enqueues_missing_pending_customer_row(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Unknown Buyer Pty Ltd",
        vendor_confidence=35.0,
        status=InvoiceStatus.VALIDATING,
        evaluation_status=EVAL_PENDING_VENDOR,
        currency="AUD",
        file_hash="pending-customer-queue-hold",
        document_type_code="DT-26",
        document_type_confidence=0.9,
        route_target="Sales Management",
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

    held = await apply_customer_hold_if_needed(db_session, loaded)
    assert held is True

    api_rows = await list_pending_customers(db_session, TESTING_TENANT_UUID)
    assert any(row.detected_name == "Unknown Buyer Pty Ltd" for row in api_rows)

    db_rows = (
        await db_session.execute(
            select(PendingCustomer).where(PendingCustomer.tenant_id == TESTING_TENANT_UUID)
        )
    ).scalars().all()
    assert any(row.detected_name == "Unknown Buyer Pty Ltd" for row in db_rows)
