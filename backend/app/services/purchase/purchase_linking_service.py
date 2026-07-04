"""PO / GRN / commercial invoice linking rules for purchase dossiers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice, InvoiceStatus, PurchaseDocumentType
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.purchase.po_reference import effective_po_reference, is_plausible_po_reference

_ACTIVE_SKIP = {
    InvoiceStatus.DUPLICATE_SKIPPED,
    InvoiceStatus.REJECTED,
}


def normalize_doc_ref(value: str | None) -> str:
    return (value or "").strip().upper()


def po_ref_for_invoice(invoice: Invoice) -> str | None:
    """Resolved PO linkage key (po_ref_no) for any purchase document."""
    return effective_po_reference(invoice.po_reference)


def invoice_no_for_link(invoice: Invoice) -> str | None:
    token = normalize_doc_ref(invoice.invoice_no)
    return token or None


async def grn_linked_to_po(session: AsyncSession, grn_invoice_id: int) -> GoodsReceipt | None:
    return (
        await session.execute(
            select(GoodsReceipt).where(GoodsReceipt.grn_invoice_id == grn_invoice_id).limit(1)
        )
    ).scalar_one_or_none()


async def find_grn_invoices_by_invoice_no(
    session: AsyncSession,
    *,
    tenant_id,
    invoice_no: str | None,
    purchase_order_id: int | None = None,
    include_linked: bool = True,
) -> list[Invoice]:
    """
    Find GRN upload rows whose invoice_no matches the commercial invoice number.

    When purchase_order_id is set, prefer GRNs already bridged to that PO.
    """
    token = normalize_doc_ref(invoice_no)
    if not token:
        return []

    rows = (
        await session.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.purchase_document_type == PurchaseDocumentType.GRN.value,
                Invoice.status.notin_(_ACTIVE_SKIP),
            )
            .order_by(Invoice.id.desc())
        )
    ).scalars().all()

    matches = [row for row in rows if invoice_no_for_link(row) == token]
    if not matches:
        return []

    if purchase_order_id is None:
        if include_linked:
            return matches
        unlinked: list[Invoice] = []
        for row in matches:
            if await grn_linked_to_po(session, row.id) is None:
                unlinked.append(row)
        return unlinked

    on_po: list[Invoice] = []
    unlinked: list[Invoice] = []
    for row in matches:
        link = await grn_linked_to_po(session, row.id)
        if link is not None and link.purchase_order_id == purchase_order_id:
            on_po.append(row)
        elif link is None:
            unlinked.append(row)

    if unlinked:
        return unlinked
    return on_po if include_linked else []


async def attach_grn_invoice_to_po(
    session: AsyncSession,
    *,
    grn_invoice: Invoice,
    po,
) -> GoodsReceipt:
    """Create or refresh GRN register row for an uploaded GRN document."""
    from app.services.purchase.purchase_match_service import _invoice_qty_and_price

    existing = await grn_linked_to_po(session, grn_invoice.id)
    if existing is not None:
        if existing.purchase_order_id != po.id:
            existing.purchase_order_id = po.id
        return existing

    loaded = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == grn_invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one_or_none()
    grn_invoice = loaded or grn_invoice
    qty, _, _ = _invoice_qty_and_price(grn_invoice)
    first_line = grn_invoice.line_items[0] if grn_invoice.line_items else None
    from app.services.master_data.uom_conversion_service import infer_uom_from_description

    grn_uom = getattr(po, "po_uom", None)
    if first_line:
        grn_uom = getattr(first_line, "uom", None) or infer_uom_from_description(
            first_line.description
        ) or grn_uom

    grn = GoodsReceipt(
        tenant_id=po.tenant_id,
        purchase_order_id=po.id,
        grn_qty=qty,
        grn_uom=grn_uom,
        grn_date=grn_invoice.invoice_date,
        receiver=None,
        condition_note="Linked via invoice_no bridge",
        grn_invoice_id=grn_invoice.id,
    )
    session.add(grn)
    await session.flush()
    return grn


async def bridge_orphan_grns_via_commercial_invoice(
    session: AsyncSession,
    *,
    commercial: Invoice,
    po,
    config: RuleBookConfigPayload | None = None,
) -> list[Invoice]:
    """
    Invoice → GRN via invoice_no, then GRN → PO through the commercial invoice bridge.
    """
    from app.services.purchase.purchase_coding_service import inherit_po_coding_to_invoice

    linked: list[Invoice] = []
    candidates = await find_grn_invoices_by_invoice_no(
        session,
        tenant_id=commercial.tenant_id,
        invoice_no=commercial.invoice_no,
        include_linked=False,
    )
    for grn_invoice in candidates:
        await attach_grn_invoice_to_po(session, grn_invoice=grn_invoice, po=po)
        inherit_po_coding_to_invoice(po, grn_invoice, config=config)
        linked.append(grn_invoice)
    return linked


def grn_has_po_ref(invoice: Invoice) -> bool:
    return is_plausible_po_reference(po_ref_for_invoice(invoice))
