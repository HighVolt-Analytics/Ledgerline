"""Production manual payment execution controls tests."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.models.tenant import Tenant
from app.models.vendor import VendorRegistry
from app.models.stripe_payments import VendorPaymentMethod
from app.schemas.payment import PaymentMarkPaidManualRequest
from app.services.payments.payment_execution_auth import PaymentExecutionUnauthorizedError
from app.services.payments.payment_execution_instruction_service import (
    PaymentExecutionBlockedError,
    create_payment_execution_instruction,
    mark_payment_paid_manual,
)
from app.services.payments.payment_execution_rules import LIMIT_BLOCK_MESSAGE
from app.tenant_ids import TESTING_TENANT_UUID


def _enable_manual_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYMENT_MANUAL_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("PAYMENT_MANUAL_EXECUTION_LIMIT_USD", "1000")
    monkeypatch.setenv("PAYMENT_EXECUTION_DISABLED", "false")
    get_settings.cache_clear()


async def _scheduled_payment(
    db_session: AsyncSession,
    *,
    amount: Decimal = Decimal("250.00"),
    suffix: str,
    with_vendor_method: bool = True,
    currency: str = "USD",
) -> Payment:
    vendor = VendorRegistry(
        tenant_id=TESTING_TENANT_UUID,
        vendor_name="Acme Supplies",
        vendor_slug=f"acme-{suffix}",
        sender_pattern="acme@example.com",
    )
    db_session.add(vendor)
    await db_session.flush()

    if with_vendor_method:
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
        currency=currency,
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
        currency=currency,
        due_date=date(2026, 7, 1),
        status=PaymentStatus.SCHEDULED,
        scheduled_date=date(2026, 6, 26),
        approvers=[{"id": "1", "name": "Approver", "role": "Approver", "state": "approved"}],
    )
    db_session.add(payment)
    await db_session.flush()
    return payment


@pytest.mark.asyncio
async def test_authorized_approver_creates_instruction(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_manual_execution(monkeypatch)
    payment = await _scheduled_payment(db_session, suffix="authorized")

    instruction, created = await create_payment_execution_instruction(
        db_session,
        TESTING_TENANT_UUID,
        payment.id,
        actor={"user_id": 1, "name": "Ops", "email": "ops@example.com", "role": "approver"},
    )

    assert created is True
    assert instruction.execution_mode == "manual_instruction"
    assert instruction.status == "instruction_created"


@pytest.mark.asyncio
async def test_unauthorized_role_blocked(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_manual_execution(monkeypatch)
    payment = await _scheduled_payment(db_session, suffix="unauth")

    with pytest.raises(PaymentExecutionUnauthorizedError, match="Tenant Admin or Approver"):
        await create_payment_execution_instruction(
            db_session,
            TESTING_TENANT_UUID,
            payment.id,
            actor={"user_id": 2, "name": "Viewer", "email": "v@example.com", "role": "viewer"},
        )


@pytest.mark.asyncio
async def test_over_limit_payment_blocked(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_manual_execution(monkeypatch)
    payment = await _scheduled_payment(db_session, suffix="limit", amount=Decimal("1500.00"))

    with pytest.raises(PaymentExecutionBlockedError, match=LIMIT_BLOCK_MESSAGE) as exc:
        await create_payment_execution_instruction(
            db_session,
            TESTING_TENANT_UUID,
            payment.id,
            actor={"user_id": 1, "name": "Ops", "email": "ops@example.com", "role": "admin"},
        )
    assert exc.value.reason_code == "limit_exceeded"


@pytest.mark.asyncio
async def test_missing_vendor_payout_method_blocked(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_manual_execution(monkeypatch)
    payment = await _scheduled_payment(db_session, suffix="novendor", with_vendor_method=False)

    with pytest.raises(ValueError, match="Vendor payout method is not verified"):
        await create_payment_execution_instruction(
            db_session,
            TESTING_TENANT_UUID,
            payment.id,
            actor={"user_id": 1, "name": "Ops", "email": "ops@example.com", "role": "admin"},
        )


@pytest.mark.asyncio
async def test_tenant_disabled_blocked(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_manual_execution(monkeypatch)
    tenant = (
        await db_session.execute(
            __import__("sqlalchemy").select(Tenant).where(Tenant.id == TESTING_TENANT_UUID)
        )
    ).scalar_one()
    tenant.settings_json = {"payment_execution_disabled": True}
    await db_session.flush()

    payment = await _scheduled_payment(db_session, suffix="tenant-off")

    with pytest.raises(PaymentExecutionBlockedError, match="disabled for this tenant") as exc:
        await create_payment_execution_instruction(
            db_session,
            TESTING_TENANT_UUID,
            payment.id,
            actor={"user_id": 1, "name": "Ops", "email": "ops@example.com", "role": "admin"},
        )
    assert exc.value.reason_code == "tenant_disabled"


@pytest.mark.asyncio
async def test_mark_paid_requires_reference_proof_and_paid_date(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_manual_execution(monkeypatch)
    payment = await _scheduled_payment(db_session, suffix="markpaid")

    with pytest.raises(ValueError, match="reference is required"):
        await mark_payment_paid_manual(
            db_session,
            TESTING_TENANT_UUID,
            payment.id,
            PaymentMarkPaidManualRequest(
                reference="   ",
                paid_date=date(2026, 6, 26),
                proof_reference="receipt-1",
            ),
            actor={"user_id": 1, "name": "Ops", "email": "ops@example.com", "role": "admin"},
        )

    await create_payment_execution_instruction(
        db_session,
        TESTING_TENANT_UUID,
        payment.id,
        actor={"user_id": 1, "name": "Ops", "email": "ops@example.com", "role": "admin"},
    )

    with pytest.raises(ValueError, match="Proof of payment reference is required"):
        await mark_payment_paid_manual(
            db_session,
            TESTING_TENANT_UUID,
            payment.id,
            PaymentMarkPaidManualRequest(
                reference="BANK-123",
                paid_date=date(2026, 6, 26),
                proof_reference="   ",
            ),
            actor={"user_id": 1, "name": "Ops", "email": "ops@example.com", "role": "admin"},
        )


@pytest.mark.asyncio
async def test_no_duplicate_instruction(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_manual_execution(monkeypatch)
    payment = await _scheduled_payment(db_session, suffix="idempotent")
    actor = {"user_id": 1, "name": "Ops", "email": "ops@example.com", "role": "admin"}

    first, created1 = await create_payment_execution_instruction(
        db_session, TESTING_TENANT_UUID, payment.id, actor=actor
    )
    second, created2 = await create_payment_execution_instruction(
        db_session, TESTING_TENANT_UUID, payment.id, actor=actor
    )

    assert created1 is True
    assert created2 is False
    assert second.id == first.id

    row, changed = await mark_payment_paid_manual(
        db_session,
        TESTING_TENANT_UUID,
        payment.id,
        PaymentMarkPaidManualRequest(
            reference="BANK-TXN-12345",
            paid_date=date(2026, 6, 26),
            proof_reference="receipt-scan-ref-99",
            note="Paid via client bank",
        ),
        actor=actor,
    )

    assert changed is True
    assert row.status == "paid"
    assert row.payment_intent == "BANK-TXN-12345"
