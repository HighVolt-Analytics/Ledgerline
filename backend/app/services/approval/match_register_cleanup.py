"""Remove purchase/sales match-register rows when a linked document is deleted."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.delivery_note import DeliveryNote
from app.models.goods_receipt import GoodsReceipt
from app.models.purchase_order import PurchaseOrder
from app.models.sales_order import SalesOrder


def purchase_order_has_document_anchor(po: PurchaseOrder) -> bool:
    """True when the PO still has a live commercial invoice, PO doc, or GRN doc."""
    if po.invoice_id is not None or po.po_document_id is not None:
        return True
    return any(g.grn_invoice_id is not None for g in (po.goods_receipts or []))


def sales_order_has_document_anchor(so: SalesOrder) -> bool:
    """True when the SO still has a live commercial invoice, SO doc, or DN doc."""
    if so.invoice_id is not None or so.so_document_id is not None:
        return True
    return any(d.dn_invoice_id is not None for d in (so.delivery_notes or []))


async def cleanup_match_registers_for_invoice(
    session: AsyncSession,
    invoice_id: int,
) -> None:
    """Unlink/delete PO·SO·GRN·DN artifacts that referenced a deleted invoice.

    FK columns use ON DELETE SET NULL, which leaves orphan register shells that
    still appear on Purchase/Sales 3-way and 2-way pages. Call this *before*
    ``session.delete(invoice)``.
    """
    affected_po_ids: set[int] = set()
    affected_so_ids: set[int] = set()

    grns = (
        await session.execute(
            select(GoodsReceipt).where(GoodsReceipt.grn_invoice_id == invoice_id)
        )
    ).scalars().all()
    for grn in grns:
        affected_po_ids.add(grn.purchase_order_id)
        await session.delete(grn)

    dns = (
        await session.execute(
            select(DeliveryNote).where(DeliveryNote.dn_invoice_id == invoice_id)
        )
    ).scalars().all()
    for dn in dns:
        affected_so_ids.add(dn.sales_order_id)
        await session.delete(dn)

    pos = (
        await session.execute(
            select(PurchaseOrder)
            .where(
                or_(
                    PurchaseOrder.invoice_id == invoice_id,
                    PurchaseOrder.po_document_id == invoice_id,
                )
            )
            .options(selectinload(PurchaseOrder.goods_receipts))
        )
    ).scalars().all()
    for po in pos:
        affected_po_ids.add(po.id)
        if po.invoice_id == invoice_id:
            po.invoice_id = None
        if po.po_document_id == invoice_id:
            po.po_document_id = None

    sos = (
        await session.execute(
            select(SalesOrder)
            .where(
                or_(
                    SalesOrder.invoice_id == invoice_id,
                    SalesOrder.so_document_id == invoice_id,
                )
            )
            .options(selectinload(SalesOrder.delivery_notes))
        )
    ).scalars().all()
    for so in sos:
        affected_so_ids.add(so.id)
        if so.invoice_id == invoice_id:
            so.invoice_id = None
        if so.so_document_id == invoice_id:
            so.so_document_id = None

    await session.flush()

    if affected_po_ids:
        orphan_pos = (
            await session.execute(
                select(PurchaseOrder)
                .where(PurchaseOrder.id.in_(affected_po_ids))
                .options(selectinload(PurchaseOrder.goods_receipts))
            )
        ).scalars().all()
        for po in orphan_pos:
            if not purchase_order_has_document_anchor(po):
                await session.delete(po)

    if affected_so_ids:
        orphan_sos = (
            await session.execute(
                select(SalesOrder)
                .where(SalesOrder.id.in_(affected_so_ids))
                .options(selectinload(SalesOrder.delivery_notes))
            )
        ).scalars().all()
        for so in orphan_sos:
            if not sales_order_has_document_anchor(so):
                await session.delete(so)

    await session.flush()
