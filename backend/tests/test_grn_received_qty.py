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
