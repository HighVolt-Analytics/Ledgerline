"""Sibling dossier upload triggers reprocess of held commercial invoices."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus, PurchaseDocumentType, SalesDocumentType
from app.models.line_item import LineItem
from app.services.dossier.dossier_reprocess_service import (
    _scheduled_sibling_reprocess,
    flush_scheduled_sibling_reprocess,
    reprocess_held_commercial_invoices_on_anchor,
)
from app.services.invoice.invoice_evaluation_service import (
    EVAL_PENDING_APPROVAL,
    ROUTE_PURCHASE,
    ROUTE_SALES,
)
from app.tenant_ids import TESTING_TENANT_UUID


@pytest.fixture(autouse=True)
def _clear_scheduled_sibling_reprocess() -> None:
    _scheduled_sibling_reprocess.clear()


@pytest.mark.asyncio
async def test_reprocess_held_commercial_on_so_anchor(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Harbour View Hotel",
        so_reference="SO-500",
        invoice_no="INV-500",
        route_target=ROUTE_SALES,
        sales_document_type=SalesDocumentType.INVOICE.value,
        status=InvoiceStatus.EXCEPTION,
        subtotal=Decimal("100"),
        total=Decimal("110"),
        raw_file_path="tenant/hv-org/invoice/held.pdf",
    )
    held.line_items = [
        LineItem(
            tenant_id=TESTING_TENANT_UUID,
            invoice_id=0,
            description="Item",
            qty=Decimal("1"),
            amount=Decimal("100"),
        )
    ]
    db_session.add(held)
    await db_session.flush()

    queued: list[list[int]] = []

    async def fake_queue(ids, *, tenant_id):
        queued.append(list(ids))

    monkeypatch.setattr(
        "app.workers.tasks.queue_invoices_for_processing",
        fake_queue,
    )

    ids = await reprocess_held_commercial_invoices_on_anchor(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_SALES,
        anchor_ref="SO-500",
        triggering_invoice_id=999,
    )
    assert held.id in ids
    assert queued == []
    await flush_scheduled_sibling_reprocess()
    assert queued == [[held.id]]
    assert held.status == InvoiceStatus.PENDING


@pytest.mark.asyncio
async def test_skip_sibling_reprocess_when_pending_approval_and_po_trigger(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    po = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Sysco Australia Pty Ltd",
        po_reference="PO-TEST-2026-001",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.PO.value,
        status=InvoiceStatus.PROCESSED,
        raw_file_path="tenant/po.pdf",
    )
    held = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Sysco Australia Pty Ltd",
        po_reference="PO-TEST-2026-001",
        invoice_no="INV-SYS-10001",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        status=InvoiceStatus.EXCEPTION,
        evaluation_status=EVAL_PENDING_APPROVAL,
        raw_file_path="tenant/invoice.pdf",
    )
    db_session.add_all([po, held])
    await db_session.flush()

    queued: list[list[int]] = []

    async def fake_queue(ids, *, tenant_id):
        queued.append(list(ids))

    monkeypatch.setattr(
        "app.workers.tasks.queue_invoices_for_processing",
        fake_queue,
    )

    ids = await reprocess_held_commercial_invoices_on_anchor(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_PURCHASE,
        anchor_ref="PO-TEST-2026-001",
        triggering_invoice_id=po.id,
    )
    assert ids == []
    assert queued == []


@pytest.mark.asyncio
async def test_skip_sibling_reprocess_when_commercial_already_pending(
    db_session: AsyncSession,
) -> None:
    held = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Sysco Australia Pty Ltd",
        po_reference="PO-TEST-2026-001",
        invoice_no="INV-SYS-10001",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        status=InvoiceStatus.PARSING,
        raw_file_path="tenant/invoice.pdf",
    )
    db_session.add(held)
    await db_session.flush()

    ids = await reprocess_held_commercial_invoices_on_anchor(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        route_target=ROUTE_PURCHASE,
        anchor_ref="PO-TEST-2026-001",
        triggering_invoice_id=999,
    )
    assert ids == []
    assert held.status == InvoiceStatus.PARSING
