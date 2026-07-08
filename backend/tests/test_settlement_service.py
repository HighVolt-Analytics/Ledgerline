from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.services.invoice.invoice_evaluation_service import ROUTE_PURCHASE, ROUTE_SALES
from app.services.payments.settlement_service import (
    ensure_payment_with_audit,
    ensure_receivable_with_audit,
    payment_skip_reason,
)
from app.tenant_ids import TESTING_TENANT_UUID


def test_payment_skip_reason_missing_due_date() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_PURCHASE,
        vendor="Acme",
        total=Decimal("100"),
        status=InvoiceStatus.PROCESSED,
    )
    assert payment_skip_reason(inv) == "missing_due_date"


@pytest.mark.asyncio
async def test_ensure_payment_with_audit_logs_settlement_skipped(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        invoice_no="PAY-SKIP",
        total=Decimal("500"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        route_target=ROUTE_PURCHASE,
        file_hash="pay-skip",
    )
    db_session.add(inv)
    await db_session.flush()

    payment = await ensure_payment_with_audit(db_session, inv)
    assert payment is None

    row = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.invoice_id == inv.id,
                AuditLog.event == "settlement_skipped",
            )
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.detail["kind"] == "payment"
    assert row.detail["reason"] == "missing_due_date"


@pytest.mark.asyncio
async def test_ensure_receivable_with_audit_logs_settlement_skipped(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Customer Co",
        invoice_no="COL-SKIP",
        total=Decimal("800"),
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        route_target=ROUTE_SALES,
        sales_document_type="invoice",
        file_hash="col-skip",
    )
    db_session.add(inv)
    await db_session.flush()

    collection = await ensure_receivable_with_audit(db_session, inv)
    assert collection is None

    row = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.invoice_id == inv.id,
                AuditLog.event == "settlement_skipped",
            )
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.detail["kind"] == "collection"
    assert row.detail["reason"] == "missing_due_date"
