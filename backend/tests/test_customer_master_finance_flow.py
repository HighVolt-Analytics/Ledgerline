"""Customer master finance flow — pending queue, VR12, counterparty sync/eval order."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.customer import CustomerMaster
from app.services.invoice.invoice_evaluation_service import (
    EVAL_PENDING_VENDOR,
    ROUTE_SALES,
    apply_invoice_evaluation,
)
from app.services.invoice.invoice_data import InvoiceData
from app.services.invoice.pipeline import _sync_counterparty_and_evaluate
from app.services.master_data.customer_master_service import (
    create_customer_master,
    list_pending_customers,
    promote_pending_customer,
)
from app.services.rule_book.extended_validations import (
    vr12_counterparty_master,
    vr12_customer_master,
    vr12_vendor_master,
)
from app.schemas.customer import CustomerMasterCreate
from app.schemas.master_data import PendingCustomerPromote
from app.schemas.rule_book_config import VendorMaster
from app.tenant_ids import TESTING_TENANT_UUID


def _customer_master(**kwargs) -> CustomerMaster:
    base = dict(
        id="cm-harbour",
        name="Harbour View Hotel",
        aliases=[],
        abn="51824753556",
        status="Active",
    )
    base.update(kwargs)
    return CustomerMaster.model_validate(base)


def _vendor_master(**kwargs) -> VendorMaster:
    base = dict(
        id="v-1",
        name="Acme Supplies Pty Ltd",
        aliases=[],
        abn="51824753556",
        status="active",
    )
    base.update(kwargs)
    return VendorMaster.model_validate(base)


def test_vr12_sales_checks_customer_master_not_vendor_master() -> None:
    data = InvoiceData(vendor="Harbour View Hotel", abn="51824753556")
    sales_result = vr12_counterparty_master(
        data,
        route_target=ROUTE_SALES,
        vendor_masters=[_vendor_master(name="Totally Different Supplier Ltd")],
        customer_masters=[_customer_master()],
    )
    assert sales_result.passed is True
    assert "Customer master OK" in sales_result.message

    purchase_result = vr12_counterparty_master(
        InvoiceData(vendor="Harbour View Hotel"),
        route_target="Purchase Management",
        vendor_masters=[_vendor_master(name="Totally Different Supplier Ltd")],
        customer_masters=[_customer_master()],
    )
    assert purchase_result.passed is False
    assert "vendor master" in purchase_result.message.lower()


def test_vr12_customer_master_unknown_customer_fails() -> None:
    data = InvoiceData(vendor="Mystery Buyer Pty Ltd")
    result = vr12_customer_master(data, customer_masters=[_customer_master()])
    assert result.passed is False
    assert "customer master" in result.message.lower()


def test_vr12_customer_master_requires_name() -> None:
    result = vr12_customer_master(InvoiceData(vendor=""), customer_masters=[_customer_master()])
    assert result.passed is False
    assert "customer name required" in result.message.lower()


@pytest.mark.asyncio
async def test_sync_counterparty_and_evaluate_re_runs_when_vendor_changes(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Highvolt Industries Pty Ltd",
        route_target="Sales Management",
        extracted_fields={
            "buyer_name": "Harbour View Hotel",
            "seller_name": "Highvolt Industries Pty Ltd",
            "perspective": "sales",
        },
        status=InvoiceStatus.MAPPING,
        currency="AUD",
        file_hash="sync-eval-order-1",
    )
    db_session.add(inv)
    await db_session.flush()

    eval_calls: list[str] = []
    sync_calls = 0

    def _sync_side_effect(invoice, *, config=None, parsed=None, org=None):
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls == 1:
            invoice.vendor = "Highvolt Industries Pty Ltd"
        else:
            invoice.vendor = "Harbour View Hotel"

    async def _track_eval(session, invoice, *, config=None, enqueue_pending=True):
        eval_calls.append((invoice.vendor or "").strip())
        from app.services.invoice.invoice_evaluation_service import InvoiceEvaluationResult, EVAL_AUTO_CODED

        invoice.evaluation_status = EVAL_AUTO_CODED
        return InvoiceEvaluationResult(
            route_target=invoice.route_target,
            matched_rule_ids=[],
            vendor_confidence=42.0,
            evaluation_status=EVAL_AUTO_CODED,
        )

    with (
        patch(
            "app.services.sales.counterparty_service.sync_invoice_counterparty",
            side_effect=_sync_side_effect,
        ),
        patch(
            "app.services.invoice.pipeline.apply_invoice_evaluation",
            new=AsyncMock(side_effect=_track_eval),
        ),
    ):
        await _sync_counterparty_and_evaluate(
            db_session,
            inv,
            parsed=None,
            config=None,
            org=None,
        )

    assert inv.vendor == "Harbour View Hotel"
    assert eval_calls == ["Highvolt Industries Pty Ltd", "Harbour View Hotel"]


@pytest.mark.asyncio
async def test_unknown_sales_buyer_enqueues_pending_customer_queue(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Mystery Buyer Pty Ltd",
        invoice_no="MB-FIN-001",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
        file_hash="pending-customer-finance-flow",
        document_type_code="DT-26",
        document_type_confidence=0.9,
        route_target=ROUTE_SALES,
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
async def test_promote_pending_customer_links_explicit_existing_master(
    db_session: AsyncSession,
) -> None:
    existing = await create_customer_master(
        db_session,
        TESTING_TENANT_UUID,
        CustomerMasterCreate(
            master_id="cm-existing",
            name="Harbour View Hotel",
            status="Active",
        ),
    )

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View",
        evaluation_status=EVAL_PENDING_VENDOR,
        route_target=ROUTE_SALES,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="promote-link-existing",
    )
    db_session.add(inv)
    await db_session.flush()

    from app.services.master_data.customer_master_service import create_pending_customer
    from app.schemas.master_data import PendingCustomerCreate

    pending = await create_pending_customer(
        db_session,
        TESTING_TENANT_UUID,
        PendingCustomerCreate(
            detected_name="Harbour View",
            source_invoice_id=inv.id,
            confidence=20.0,
        ),
    )

    promoted = await promote_pending_customer(
        db_session,
        TESTING_TENANT_UUID,
        pending.id,
        PendingCustomerPromote(master_id=existing.id, name="Harbour View"),
    )
    assert promoted.id == existing.id
