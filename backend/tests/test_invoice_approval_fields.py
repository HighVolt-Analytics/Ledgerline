
from app.tenant_ids import PLATFORM_TENANT_UUID, TESTING_TENANT_UUID
"""Approval must preserve user-corrected invoice fields and reach processed state."""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.services.approval.approval_pipeline_service import (
    apply_human_approval_processing_defaults,
    human_approval_may_bypass_validation,
    human_approved_payable_bypass,
    payable_fields_complete,
)
from app.services.rule_book.validator import ValidationResult
from app.services.approval.approval_service import approve_invoice_for_reprocess
from app.services.audit.audit_service import log_event


@pytest.mark.asyncio
async def test_payable_fields_complete() -> None:
    complete = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="ram",
        total=Decimal("110"),
        due_date=date(2026, 6, 30),
        currency="AUD",
        file_hash="x",
    )
    incomplete = Invoice(tenant_id=TESTING_TENANT_UUID, vendor="ram", currency="AUD", file_hash="y")
    assert payable_fields_complete(complete) is True
    assert payable_fields_complete(incomplete) is False


@pytest.mark.asyncio
async def test_human_approved_payable_bypass(db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="ram",
        total=Decimal("110"),
        due_date=date(2026, 6, 30),
        currency="AUD",
        file_hash="bypass-1",
        status=InvoiceStatus.EXCEPTION,
    )
    db_session.add(inv)
    await db_session.flush()
    assert await human_approved_payable_bypass(db_session, inv) is False

    await log_event(db_session, "invoice_approved", invoice_id=inv.id)
    assert await human_approved_payable_bypass(db_session, inv) is True


def test_human_approval_defaults_do_not_clear_vendor_evaluation() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        evaluation_status="pending_vendor",
        purchase_document_type="po",
        currency="AUD",
        file_hash="defaults-1",
    )
    apply_human_approval_processing_defaults(inv)
    assert inv.evaluation_status == "pending_vendor"
    assert inv.purchase_document_type == "invoice"


def test_human_approval_may_not_bypass_vr12_failure() -> None:
    assert human_approval_may_bypass_validation(
        [ValidationResult("VR03", False, "missing field")]
    )
    assert not human_approval_may_bypass_validation(
        [ValidationResult("VR12", False, "Vendor not found in vendor master")]
    )


@pytest.mark.asyncio
async def test_approve_preserves_corrected_fields(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
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
        "app.services.approval.approval_service.stored_file_available",
        lambda *args, **kwargs: True,
    )

    await approve_invoice_for_reprocess(db_session, inv)

    assert inv.status == InvoiceStatus.PENDING
    assert inv.vendor == "ram"
    assert inv.total == Decimal("110.00")
    assert inv.due_date == date(2026, 7, 1)
    assert inv.billing_address == "LedgerLine Test Tenant"


@pytest.mark.asyncio
async def test_approve_allows_missing_due_date_without_compulsory_fields(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        total=Decimal("110.00"),
        due_date=None,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="approve-no-due-1",
        raw_file_path="/tmp/invoice.pdf",
        document_type_code="DT-08",
    )
    db_session.add(inv)
    await db_session.flush()

    monkeypatch.setattr(
        "app.services.approval.approval_service.stored_file_available",
        lambda *args, **kwargs: True,
    )

    await approve_invoice_for_reprocess(db_session, inv)
    assert inv.status == InvoiceStatus.PENDING


@pytest.mark.asyncio
async def test_reprocess_preserves_manual_edits(db_session: AsyncSession) -> None:
    from app.services.invoice.invoice_reset import requeue_invoice_for_pipeline
    from app.services.invoice.invoice_edit_service import update_invoice_fields
    from app.schemas.invoice import InvoiceUpdateRequest

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="reprocess-preserve-1",
        vendor="Acme",
        total=Decimal("99.00"),
        due_date=date(2026, 8, 1),
        po_reference="PO-100",
    )
    db_session.add(inv)
    await db_session.flush()

    await update_invoice_fields(
        db_session,
        inv,
        InvoiceUpdateRequest(vendor="Corrected Vendor", po_reference="PO-200"),
        actor_name="tester",
    )

    await requeue_invoice_for_pipeline(db_session, inv, preserve_extracted_fields=True)

    assert inv.status == InvoiceStatus.PENDING
    assert inv.vendor == "Corrected Vendor"
    assert inv.po_reference == "PO-200"
    assert inv.total == Decimal("99.00")


@pytest.mark.asyncio
async def test_approve_requires_compulsory_fields_when_configured(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.schemas.document_type import DocumentTypeDefinition
    from app.services.approval.approval_service import _assert_invoice_ready_for_approval

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        total=Decimal("99"),
        due_date=date(2026, 8, 1),
        currency="AUD",
        file_hash="approve-compulsory-1",
        document_type_code="DT-08",
    )
    definition = DocumentTypeDefinition(
        code="DT-08",
        title="Direct expense",
        shortTitle="Direct",
        klass="Transactional",
        posting="Yes",
        recognition_mode="signals", recognition_signals=["heading_invoice"], llm_prompt="",
        routeTarget="Expenses Management",
        extractionFields=["vendor", "invoice_no", "total"],
        requiredFields=["vendor", "invoice_no", "total"],
    )
    with pytest.raises(ValueError, match="invoice_no"):
        _assert_invoice_ready_for_approval(inv, definition=definition)

    inv.invoice_no = "INV-1"
    _assert_invoice_ready_for_approval(inv, definition=definition)


@pytest.mark.asyncio
async def test_patch_billing_address(client: AsyncClient, db_session: AsyncSession) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
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
