"""Purchase dossier linking: PO / GRN / commercial invoice rules."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice, InvoiceStatus, PurchaseDocumentType
from app.models.line_item import LineItem
from app.models.purchase_order import PurchaseOrder
from app.services.invoice.invoice_evaluation_service import ROUTE_PURCHASE
from app.services.purchase.purchase_document_service import sync_purchase_document
from app.tenant_ids import TESTING_TENANT_UUID


async def _add_line(session: AsyncSession, inv: Invoice, qty: str = "10", price: str = "50") -> Invoice:
    session.add(
        LineItem(
            tenant_id=inv.tenant_id,
            invoice_id=inv.id,
            description="Widgets",
            qty=Decimal(qty),
            unit_price=Decimal(price),
            amount=Decimal(qty) * Decimal(price),
        )
    )
    await session.flush()
    return (
        await session.execute(
            select(Invoice).where(Invoice.id == inv.id).options(selectinload(Invoice.line_items))
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_grn_with_po_ref_links_directly(db_session: AsyncSession) -> None:
    po_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Sysco",
        po_reference="PO-LINK-100",
        invoice_no="PO-LINK-100",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.PO.value,
        subtotal=Decimal("500.00"),
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(po_doc)
    await db_session.flush()
    await _add_line(db_session, po_doc)

    po_row = await sync_purchase_document(db_session, po_doc)
    assert po_row is not None

    grn_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Sysco",
        po_reference="PO-LINK-100",
        invoice_no="GRN-LINK-100",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.GRN.value,
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(grn_doc)
    await db_session.flush()
    await _add_line(db_session, grn_doc)

    linked_po = await sync_purchase_document(db_session, grn_doc)
    assert linked_po is not None
    grn_row = (
        await db_session.execute(
            select(GoodsReceipt).where(GoodsReceipt.grn_invoice_id == grn_doc.id)
        )
    ).scalar_one_or_none()
    assert grn_row is not None
    assert grn_row.purchase_order_id == po_row.id


@pytest.mark.asyncio
async def test_grn_without_po_ref_waits_then_bridges_via_invoice_no(db_session: AsyncSession) -> None:
    shared_invoice_no = "INV-BRIDGE-900"

    grn_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Sysco",
        po_reference=None,
        invoice_no=shared_invoice_no,
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.GRN.value,
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(grn_doc)
    await db_session.flush()
    await _add_line(db_session, grn_doc)

    assert await sync_purchase_document(db_session, grn_doc) is None
    orphan_grn = (
        await db_session.execute(
            select(GoodsReceipt).where(GoodsReceipt.grn_invoice_id == grn_doc.id)
        )
    ).scalar_one_or_none()
    assert orphan_grn is None

    po_doc = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Sysco",
        po_reference="PO-BRIDGE-200",
        invoice_no="PO-BRIDGE-200",
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.PO.value,
        subtotal=Decimal("500.00"),
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(po_doc)
    await db_session.flush()
    await _add_line(db_session, po_doc)
    po_row = await sync_purchase_document(db_session, po_doc)
    assert po_row is not None

    commercial = Invoice(
        tenant_id=TESTING_TENANT_UUID,
        vendor="Sysco",
        po_reference="PO-BRIDGE-200",
        invoice_no=shared_invoice_no,
        route_target=ROUTE_PURCHASE,
        purchase_document_type=PurchaseDocumentType.INVOICE.value,
        subtotal=Decimal("500.00"),
        gst=Decimal("50.00"),
        total=Decimal("550.00"),
        status=InvoiceStatus.MAPPING,
    )
    db_session.add(commercial)
    await db_session.flush()
    await _add_line(db_session, commercial)

    linked_po = await sync_purchase_document(db_session, commercial)
    assert linked_po is not None
    assert linked_po.invoice_id == commercial.id

    grn_row = (
        await db_session.execute(
            select(GoodsReceipt).where(GoodsReceipt.grn_invoice_id == grn_doc.id)
        )
    ).scalar_one_or_none()
    assert grn_row is not None
    assert grn_row.purchase_order_id == po_row.id

    po_check = (
        await db_session.execute(
            select(PurchaseOrder).where(PurchaseOrder.id == po_row.id)
        )
    ).scalar_one()
    assert po_check.invoice_id == commercial.id
