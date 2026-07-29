"""GRN received quantity resolution for purchase register and 3-way match."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice, PurchaseDocumentType
from app.models.purchase_order import PurchaseOrder
from app.services.invoice.invoice_evaluation_service import ROUTE_PURCHASE
from app.services.purchase.purchase_linking_service import attach_grn_invoice_to_po
from app.services.purchase.purchase_match_service import resolve_grn_received_qty
from app.tenant_ids import TESTING_TENANT_UUID

GRN_BODY = """
GOODS RECEIPT NOTE
Sysco Australia Pty Ltd
GRN Number: GRN-TEST-001
PO Reference: PO-TEST-2026-001
Receipt Date: 10 June 2026

Description                    Qty Received   Condition
Fresh seasonal produce                  20   Good
"""


def test_resolve_grn_received_qty_from_document_text() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        document_text=GRN_BODY,
        purchase_document_type=PurchaseDocumentType.GRN.value,
    )
    assert resolve_grn_received_qty(inv) == Decimal("20")


def test_resolve_grn_received_qty_falls_back_to_po_qty() -> None:
    inv = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        purchase_document_type=PurchaseDocumentType.GRN.value,
    )
    assert resolve_grn_received_qty(inv, po_qty=Decimal("10")) == Decimal("10")


@pytest.mark.asyncio
async def test_attach_grn_refreshes_qty_on_relink(db_session: AsyncSession) -> None:
    po = PurchaseOrder(
        tenant_id=TESTING_TENANT_UUID,
        po_number="PO-TEST-2026-001",
        vendor="Sysco Australia Pty Ltd",
        po_qty=Decimal("20"),
        po_unit_price=Decimal("50"),
    )
    db_session.add(po)
    await db_session.flush()

    grn_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Sysco Australia Pty Ltd",
        po_reference="PO-TEST-2026-001",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.GRN.value,
        document_text=GRN_BODY,
    )
    db_session.add(grn_doc)
    await db_session.flush()

    grn_row = await attach_grn_invoice_to_po(db_session, grn_invoice=grn_doc, po=po)
    assert grn_row.grn_qty == Decimal("20")

    grn_doc.document_text = GRN_BODY.replace("20", "18")
    await db_session.flush()
    grn_row = await attach_grn_invoice_to_po(db_session, grn_invoice=grn_doc, po=po)
    assert grn_row.grn_qty == Decimal("18")

    rows = (
        await db_session.execute(
            select(GoodsReceipt).where(GoodsReceipt.grn_invoice_id == grn_doc.id)
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_attach_grn_no_missing_greenlet_after_flush(db_session: AsyncSession) -> None:
    """New GRN after flush has unloaded .lines — populate must not lazy-load (async)."""
    from sqlalchemy.orm import attributes

    from app.models.purchase_order_line import PurchaseOrderLine
    from app.services.matching.line_sync import populate_grn_lines_from_invoice

    po = PurchaseOrder(
        tenant_id=TESTING_TENANT_UUID,
        po_number="PO-GREENLET-001",
        vendor="Sysco Australia Pty Ltd",
        po_qty=Decimal("20"),
        po_unit_price=Decimal("50"),
    )
    db_session.add(po)
    await db_session.flush()
    attributes.set_committed_value(
        po,
        "lines",
        [
            PurchaseOrderLine(
                tenant_id=TESTING_TENANT_UUID,
                line_no=1,
                description="Fresh produce",
                qty=Decimal("20"),
                unit_price=Decimal("50"),
                line_value=Decimal("1000"),
            )
        ],
    )
    await db_session.flush()

    grn_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Sysco Australia Pty Ltd",
        po_reference="PO-GREENLET-001",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.GRN.value,
        document_text=GRN_BODY,
    )
    db_session.add(grn_doc)
    await db_session.flush()

    # Mimic attach_grn path: persist header, then populate lines while .lines is unloaded.
    grn = GoodsReceipt(
        tenant_id=TESTING_TENANT_UUID,
        purchase_order_id=po.id,
        grn_qty=Decimal("0"),
        grn_invoice_id=grn_doc.id,
    )
    db_session.add(grn)
    await db_session.flush()
    db_session.expire(grn, ["lines"])

    populate_grn_lines_from_invoice(
        grn, po=po, invoice=grn_doc, fallback_qty=Decimal("20")
    )
    await db_session.flush()
    assert grn.grn_qty == Decimal("20")
    assert len(grn.lines) == 1

    # Full attach path must also succeed without MissingGreenlet.
    po2 = PurchaseOrder(
        tenant_id=TESTING_TENANT_UUID,
        po_number="PO-GREENLET-002",
        vendor="Sysco Australia Pty Ltd",
        po_qty=Decimal("20"),
        po_unit_price=Decimal("50"),
    )
    db_session.add(po2)
    await db_session.flush()
    po2 = (
        await db_session.execute(
            select(PurchaseOrder)
            .where(PurchaseOrder.id == po2.id)
            .options(selectinload(PurchaseOrder.lines))
        )
    ).scalar_one()

    grn_doc2 = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Sysco Australia Pty Ltd",
        po_reference="PO-GREENLET-002",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.GRN.value,
        document_text=GRN_BODY,
    )
    db_session.add(grn_doc2)
    await db_session.flush()

    linked = await attach_grn_invoice_to_po(db_session, grn_invoice=grn_doc2, po=po2)
    assert linked.grn_qty == Decimal("20")
