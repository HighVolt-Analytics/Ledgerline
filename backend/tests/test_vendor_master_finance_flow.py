"""Vendor master finance flow — pending queue, VR12, counterparty sync/eval order."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.customer import CustomerMaster
from app.schemas.master_data import PendingVendorCreate, PendingVendorPromote, VendorMasterCreate
from app.schemas.rule_book_config import VendorMaster
from app.services.invoice.invoice_data import InvoiceData
from app.services.invoice.invoice_evaluation_service import (
    EVAL_PENDING_VENDOR,
    ROUTE_PURCHASE,
    apply_invoice_evaluation,
)
from app.services.invoice.pipeline import (
    _finalize_vendor_counterparty,
    _sync_counterparty_and_evaluate,
)
from app.services.master_data.master_data_service import (
    create_vendor_master,
    list_pending_vendors,
    promote_pending_vendor,
)
from app.services.rule_book.extended_validations import vr12_counterparty_master, vr12_vendor_master
from app.tenant_ids import TESTING_TENANT_UUID


def _vendor_master(**kwargs) -> VendorMaster:
    base = dict(
        id="vm-acme",
        name="Acme Supplies Pty Ltd",
        aliases=["Acme"],
        abn="51824753556",
        status="active",
    )
    base.update(kwargs)
    return VendorMaster.model_validate(base)


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


def test_vr12_purchase_checks_vendor_master_not_customer_master() -> None:
    data = InvoiceData(vendor="Acme Supplies Pty Ltd", abn="51824753556")
    purchase_result = vr12_counterparty_master(
        data,
        route_target=ROUTE_PURCHASE,
        vendor_masters=[_vendor_master()],
        customer_masters=[_customer_master(name="Totally Different Buyer Ltd")],
    )
    assert purchase_result.passed is True
    assert "Vendor master OK" in purchase_result.message

    sales_result = vr12_counterparty_master(
        InvoiceData(vendor="Acme Supplies Pty Ltd"),
        route_target="Sales Management",
        vendor_masters=[_vendor_master()],
        customer_masters=[_customer_master(name="Totally Different Buyer Ltd")],
    )
    assert sales_result.passed is False
    assert "customer master" in sales_result.message.lower()


def test_vr12_vendor_master_unknown_supplier_fails() -> None:
    data = InvoiceData(vendor="Mystery Supplies Pty Ltd")
    result = vr12_vendor_master(data, vendor_masters=[_vendor_master()])
    assert result.passed is False
    assert "vendor master" in result.message.lower()


def test_finalize_vendor_counterparty_canonicalizes_alias() -> None:
    cfg = type("Cfg", (), {"vendor_masters": [_vendor_master()]})()
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        route_target=ROUTE_PURCHASE,
        extracted_fields={
            "perspective": "purchase",
            "seller_name": "Acme",
        },
    )
    _finalize_vendor_counterparty(
        inv,
        parsed=InvoiceData(vendor="Acme", abn="51824753556"),
        config=cfg,
    )
    assert inv.vendor == "Acme Supplies Pty Ltd"


@pytest.mark.asyncio
async def test_sync_counterparty_and_evaluate_uses_canonical_vendor_before_eval(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        route_target=ROUTE_PURCHASE,
        extracted_fields={
            "seller_name": "Acme Supplies Pty Ltd",
            "buyer_name": "Highvolt Industries Pty Ltd",
            "perspective": "purchase",
        },
        status=InvoiceStatus.MAPPING,
        currency="AUD",
        file_hash="vendor-sync-eval-canonical",
    )
    db_session.add(inv)
    await db_session.flush()

    eval_vendors: list[str] = []
    cfg = type("Cfg", (), {"vendor_masters": [_vendor_master()]})()

    def _sync_side_effect(invoice, *, config=None, parsed=None, org=None):
        invoice.vendor = "Acme"

    async def _track_eval(session, invoice, *, config=None, enqueue_pending=True):
        eval_vendors.append((invoice.vendor or "").strip())
        from app.services.invoice.invoice_evaluation_service import EVAL_AUTO_CODED, InvoiceEvaluationResult

        invoice.evaluation_status = EVAL_AUTO_CODED
        return InvoiceEvaluationResult(
            route_target=invoice.route_target,
            matched_rule_ids=[],
            vendor_confidence=88.0,
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
            parsed=InvoiceData(vendor="Acme", abn="51824753556"),
            config=cfg,
            org=None,
        )

    assert inv.vendor == "Acme Supplies Pty Ltd"
    assert eval_vendors
    assert all(name == "Acme Supplies Pty Ltd" for name in eval_vendors)


@pytest.mark.asyncio
async def test_unknown_purchase_seller_enqueues_pending_vendor_queue(
    db_session: AsyncSession,
) -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Mystery Supplies Pty Ltd",
        invoice_no="MYS-V-001",
        status=InvoiceStatus.MAPPING,
        currency="AUD",
        file_hash="pending-vendor-finance-flow",
        document_type_code="DT-01",
        document_type_confidence=0.9,
        route_target=ROUTE_PURCHASE,
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
async def test_promote_pending_vendor_links_explicit_existing_master(
    db_session: AsyncSession,
) -> None:
    existing = await create_vendor_master(
        db_session,
        TESTING_TENANT_UUID,
        VendorMasterCreate(
            master_id="vm-existing",
            name="Acme Supplies Pty Ltd",
            status="Active",
        ),
    )

    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Acme",
        evaluation_status=EVAL_PENDING_VENDOR,
        route_target=ROUTE_PURCHASE,
        status=InvoiceStatus.EXCEPTION,
        currency="AUD",
        file_hash="promote-vendor-link-existing",
    )
    db_session.add(inv)
    await db_session.flush()

    from app.services.master_data.master_data_service import create_pending_vendor

    pending = await create_pending_vendor(
        db_session,
        TESTING_TENANT_UUID,
        PendingVendorCreate(
            detected_name="Acme",
            source_invoice_id=inv.id,
            confidence=20.0,
        ),
    )

    promoted = await promote_pending_vendor(
        db_session,
        TESTING_TENANT_UUID,
        pending.id,
        PendingVendorPromote(master_id=existing.id, name="Acme"),
    )
    assert promoted.id == existing.id
