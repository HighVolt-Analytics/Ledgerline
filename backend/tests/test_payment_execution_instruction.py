"""Manual payment execution instruction orchestration tests."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.models.vendor import VendorRegistry
from app.models.stripe_payments import VendorPaymentMethod
from app.schemas.payment import PaymentMarkPaidManualRequest
from app.services.payment_execution_instruction_service import (
    PaymentExecutionBlockedError,
    create_payment_execution_instruction,
    mark_payment_paid_manual,
)
from app.tenant_ids import TESTING_TENANT_UUID


async def _scheduled_payment(
    db_session: AsyncSession,
    *,
    amount: Decimal = Decimal("250.00"),
    suffix: str,
) -> Payment:
    vendor = VendorRegistry(
        tenant_id=TESTING_TENANT_UUID,
        vendor_name="Acme Supplies",
        vendor_slug=f"acme-{suffix}",
        sender_pattern="acme@example.com",
    )
    db_session.add(vendor)
    await db_session.flush()

    db_session.add(
        VendorPaymentMethod(
            tenant_id=TESTING_TENANT_UUID,
            vendor_id=vendor.id,
            method_type="manual_bank",
            display_label="Business account",
            status="verified",
            is_default=True,
        )
    )

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme Supplies",
        status=InvoiceStatus.PROCESSED,
        currency="AUD",
        file_hash=f"manual-exec-{suffix}",
        due_date=date(2026, 7, 1),
        total=amount,
        storage_vendor_slug=vendor.vendor_slug,
    )
    db_session.add(inv)
    await db_session.flush()

    payment = Payment(
        tenant_id=TESTING_TENANT_UUID,
        invoice_id=inv.id,
        vendor_registry_id=vendor.id,
        vendor="Acme Supplies",
        amount=amount,
        currency="AUD",
        due_date=date(2026, 7, 1),
        status=PaymentStatus.SCHEDULED,
        scheduled_date=date(2026, 6, 26),
        approvers=[{"id": "1", "name": "Approver", "role": "Approver", "state": "approved"}],
    )
    db_session.add(payment)
    await db_session.flush()
    return payment


@pytest.mark.asyncio
async def test_create_instruction_blocked_when_manual_disabled(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAYMENT_MANUAL_EXECUTION_ENABLED", "false")
    get_settings.cache_clear()
    payment = await _scheduled_payment(db_session, suffix="disabled")

    with pytest.raises(PaymentExecutionBlockedError, match="not enabled"):
        await create_payment_execution_instruction(
            db_session,
            TESTING_TENANT_UUID,
            payment.id,
            actor={"user_id": 1, "name": "Ops", "email": "ops@example.com"},
        )


@pytest.mark.asyncio
async def test_create_and_mark_paid_manual_flow(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAYMENT_MANUAL_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("PAYMENT_MANUAL_EXECUTION_LIMIT_AUD", "1000")
    get_settings.cache_clear()

    payment = await _scheduled_payment(db_session, suffix="flow")

    instruction, created = await create_payment_execution_instruction(
        db_session,
        TESTING_TENANT_UUID,
        payment.id,
        actor={"user_id": 1, "name": "Ops", "email": "ops@example.com"},
    )

    assert created is True
    assert instruction.execution_mode == "manual_instruction"
    assert instruction.status == "instruction_created"
    assert instruction.vendor_name == "Acme Supplies"
    assert instruction.amount == 250.0

    instruction2, created2 = await create_payment_execution_instruction(
        db_session,
        TESTING_TENANT_UUID,
        payment.id,
        actor={"user_id": 1, "name": "Ops", "email": "ops@example.com"},
    )
    assert created2 is False
    assert instruction2.id == instruction.id

    row, changed = await mark_payment_paid_manual(
        db_session,
        TESTING_TENANT_UUID,
        payment.id,
        PaymentMarkPaidManualRequest(reference="BANK-TXN-12345", note="Paid via client bank"),
        actor={"user_id": 1, "name": "Ops", "email": "ops@example.com"},
    )

    assert changed is True
    assert row.status == "paid"
    assert row.payment_intent == "BANK-TXN-12345"


@pytest.mark.asyncio
async def test_mark_paid_requires_reference(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAYMENT_MANUAL_EXECUTION_ENABLED", "true")
    get_settings.cache_clear()
    payment = await _scheduled_payment(db_session, suffix="ref")

    with pytest.raises(ValueError, match="reference is required"):
        await mark_payment_paid_manual(
            db_session,
            TESTING_TENANT_UUID,
            payment.id,
            PaymentMarkPaidManualRequest(reference="   "),
            actor={"user_id": 1, "name": "Ops", "email": "ops@example.com"},
        )
