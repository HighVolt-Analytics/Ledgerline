"""Vendor hold outcome audit events for pipeline transparency."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.vendor_master import VendorMasterRecord
from app.services.master_data.vendor_hold_service import apply_vendor_hold_if_needed
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.mark.asyncio
async def test_vendor_hold_logs_cleared_for_known_master(db_session: AsyncSession) -> None:
    db_session.add(
        VendorMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="vm-reg",
            name="Registered Supplier Co",
            default_ledger="5100",
            status="Active",
        )
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Registered Supplier Co",
        route_target="Purchase Management",
        vendor_confidence=95.0,
        status=InvoiceStatus.VALIDATING,
        currency="AUD",
        file_hash="vh-audit-1",
    )
    db_session.add(inv)
    await db_session.flush()

    held = await apply_vendor_hold_if_needed(db_session, inv)
    assert held is False

    events = (
        await db_session.execute(
            select(AuditLog.event, AuditLog.detail).where(
                AuditLog.invoice_id == inv.id,
                AuditLog.event.in_(
                    (
                        "vendor_registration_cleared",
                        "vendor_registration_waived",
                        "vendor_registration_hold",
                    )
                ),
            )
        )
    ).all()
    assert len(events) == 1
    assert events[0][0] == "vendor_registration_cleared"


@pytest.mark.asyncio
async def test_vendor_hold_logs_waived_when_registration_not_required(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Team Cafe",
        route_target="Team Expenses",
        status=InvoiceStatus.VALIDATING,
        currency="AUD",
        file_hash="vh-audit-2",
    )
    db_session.add(inv)
    await db_session.flush()

    held = await apply_vendor_hold_if_needed(db_session, inv)
    assert held is False

    event = (
        await db_session.execute(
            select(AuditLog.event).where(
                AuditLog.invoice_id == inv.id,
                AuditLog.event == "vendor_registration_waived",
            )
        )
    ).scalar_one_or_none()
    assert event == "vendor_registration_waived"


@pytest.mark.asyncio
async def test_vendor_hold_dedupes_repeated_checks(db_session: AsyncSession) -> None:
    db_session.add(
        VendorMasterRecord(
            tenant_id=TESTING_TENANT_UUID,
            master_id="vm-dedupe",
            name="Dedupe Vendor",
            default_ledger="5100",
            status="Active",
        )
    )
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Dedupe Vendor",
        route_target="Purchase Management",
        vendor_confidence=90.0,
        status=InvoiceStatus.VALIDATING,
        currency="AUD",
        file_hash="vh-audit-3",
    )
    db_session.add(inv)
    await db_session.flush()

    await apply_vendor_hold_if_needed(db_session, inv)
    await apply_vendor_hold_if_needed(db_session, inv)
    await apply_vendor_hold_if_needed(db_session, inv)

    count = (
        await db_session.execute(
            select(AuditLog.id).where(
                AuditLog.invoice_id == inv.id,
                AuditLog.event == "vendor_registration_cleared",
            )
        )
    ).all()
    assert len(count) == 1


@pytest.mark.asyncio
async def test_vendor_hold_moves_processed_invoice_to_exception(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Unknown Supplier",
        route_target="Purchase Management",
        document_type_code="DT-01",
        status=InvoiceStatus.PROCESSED,
        evaluation_status="auto_coded",
        currency="AUD",
        file_hash="vh-processed-1",
    )
    db_session.add(inv)
    await db_session.flush()

    held = await apply_vendor_hold_if_needed(db_session, inv)
    assert held is True
    assert inv.status == InvoiceStatus.EXCEPTION
    assert inv.evaluation_status == "pending_vendor"
    assert inv.vendor_confidence == 0.0


@pytest.mark.asyncio
async def test_vendor_hold_purchase_unknown_even_at_high_confidence(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Totally Unknown Pty Ltd",
        route_target="Purchase Management",
        vendor_confidence=92.0,
        status=InvoiceStatus.VALIDATING,
        currency="AUD",
        file_hash="vh-audit-4",
    )
    db_session.add(inv)
    await db_session.flush()

    held = await apply_vendor_hold_if_needed(db_session, inv)
    assert held is True
    assert inv.evaluation_status == "pending_vendor"
    assert inv.status == InvoiceStatus.EXCEPTION
