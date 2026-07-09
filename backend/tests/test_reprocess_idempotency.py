"""Reprocess idempotency and deferred-reset tests."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.line_item import LineItem
from app.services.invoice.invoice_reset import requeue_invoice_for_pipeline, reset_invoice_for_reprocess
from app.services.invoice.processing_override_catalog import consume_deferred_full_reset
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_deferred_requeue_preserves_extracted_fields(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="deferred-reset-1",
        vendor="ACME LTD",
        invoice_no="INV-100",
        extracted_fields={"invoice_no": "INV-100"},
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            description="Widget",
            qty=Decimal("2"),
        )
    )
    await db_session.flush()

    await requeue_invoice_for_pipeline(db_session, inv, preserve_extracted_fields=False)
    await db_session.flush()

    assert inv.status == InvoiceStatus.PENDING
    assert inv.vendor == "ACME LTD"
    assert inv.invoice_no == "INV-100"
    assert consume_deferred_full_reset(inv) is True


@pytest.mark.asyncio
async def test_reset_invoice_clears_line_items_without_duplicating(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.PENDING,
        currency="AUD",
        file_hash="reset-li-1",
        vendor="ACME LTD",
        invoice_no="INV-200",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add(
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=inv.id,
            description="Line A",
            qty=Decimal("1"),
        )
    )
    await db_session.flush()

    await reset_invoice_for_reprocess(db_session, inv)
    await db_session.flush()
    await db_session.refresh(inv, attribute_names=["line_items"])

    assert inv.vendor is None
    assert inv.invoice_no is None
    assert inv.line_items == []
