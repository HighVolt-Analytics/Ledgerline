
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Payment single-approval workflow tests."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.services.payment_service import approve_payment


@pytest.mark.asyncio
async def test_approve_payment_from_awaiting(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="ram",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="pay-approve-1",
        due_date=date(2026, 6, 30),
        total=Decimal("110.00"),
    )
    db_session.add(inv)
    await db_session.flush()

    payment = Payment(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=inv.id,
        vendor="ram",
        amount=Decimal("110.00"),
        currency="AUD",
        due_date=date(2026, 6, 30),
        status=PaymentStatus.AWAITING,
        approvers=[],
    )
    db_session.add(payment)
    await db_session.flush()

    row, changed = await approve_payment(
        db_session,
        payment.tenant_id,
        payment.id,
        actor={"user_id": 42, "name": "Test User", "email": "test@example.com"},
    )

    assert changed is True
    assert row.status == "scheduled"
    assert row.scheduled_date == date.today()
    assert len(row.approvers) == 1
    assert row.approvers[0]["state"] == "approved"
    assert row.approvers[0]["id"] == "42"


@pytest.mark.asyncio
async def test_approve_payment_idempotent_when_scheduled(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="ram",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="pay-approve-2",
    )
    db_session.add(inv)
    await db_session.flush()

    payment = Payment(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=inv.id,
        vendor="ram",
        amount=Decimal("110.00"),
        currency="AUD",
        status=PaymentStatus.SCHEDULED,
        scheduled_date=date(2026, 6, 26),
        approvers=[{"id": "42", "name": "Test User", "role": "Approver", "state": "approved"}],
    )
    db_session.add(payment)
    await db_session.flush()

    row, changed = await approve_payment(
        db_session,
        payment.tenant_id,
        payment.id,
        actor={"user_id": 99, "name": "Other User", "email": "other@example.com"},
    )

    assert changed is False
    assert row.status == "scheduled"
    assert row.approvers[0]["id"] == "42"


@pytest.mark.asyncio
async def test_approve_payment_rejects_queue(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="ram",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash="pay-approve-3",
    )
    db_session.add(inv)
    await db_session.flush()

    payment = Payment(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=inv.id,
        vendor="ram",
        amount=Decimal("110.00"),
        currency="AUD",
        status=PaymentStatus.QUEUE,
    )
    db_session.add(payment)
    await db_session.flush()

    with pytest.raises(ValueError, match="cannot be approved"):
        await approve_payment(
            db_session,
            payment.tenant_id,
            payment.id,
            actor={"user_id": 1, "name": "Test", "email": "t@example.com"},
        )
