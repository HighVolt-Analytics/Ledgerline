"""SO / DN / commercial invoice linking rules for sales dossiers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.delivery_note import DeliveryNote
from app.models.invoice import Invoice, InvoiceStatus, SalesDocumentType
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.so_reference import (
    ensure_invoice_so_reference,
    is_plausible_so_reference,
    resolve_so_reference_from_invoice,
)

_ACTIVE_SKIP = {
    InvoiceStatus.DUPLICATE_SKIPPED,
    InvoiceStatus.REJECTED,
}


def normalize_doc_ref(value: str | None) -> str:
    return (value or "").strip().upper()


def so_ref_for_invoice(invoice: Invoice) -> str | None:
    """Resolved SO linkage key for any sales document."""
    return resolve_so_reference_from_invoice(invoice)


def invoice_no_for_link(invoice: Invoice) -> str | None:
    token = normalize_doc_ref(invoice.invoice_no)
    return token or None


async def dn_linked_to_so(session: AsyncSession, dn_invoice_id: int) -> DeliveryNote | None:
    return (
        await session.execute(
            select(DeliveryNote).where(DeliveryNote.dn_invoice_id == dn_invoice_id).limit(1)
        )
    ).scalar_one_or_none()


async def find_dn_invoices_by_invoice_no(
    session: AsyncSession,
    *,
    tenant_id,
    invoice_no: str | None,
    sales_order_id: int | None = None,
    include_linked: bool = True,
) -> list[Invoice]:
    """Find DN upload rows whose invoice_no matches the commercial invoice number."""
    token = normalize_doc_ref(invoice_no)
    if not token:
        return []

    rows = (
        await session.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.sales_document_type == SalesDocumentType.DN.value,
                Invoice.status.notin_(_ACTIVE_SKIP),
            )
            .order_by(Invoice.id.desc())
        )
    ).scalars().all()

    matches = [row for row in rows if invoice_no_for_link(row) == token]
    if not matches:
        return []

    if sales_order_id is None:
        if include_linked:
            return matches
        unlinked: list[Invoice] = []
        for row in matches:
            if await dn_linked_to_so(session, row.id) is None:
                unlinked.append(row)
        return unlinked

    on_so: list[Invoice] = []
    unlinked: list[Invoice] = []
    for row in matches:
        link = await dn_linked_to_so(session, row.id)
        if link is not None and link.sales_order_id == sales_order_id:
            on_so.append(row)
        elif link is None:
            unlinked.append(row)

    if unlinked:
        return unlinked
    return on_so if include_linked else []


async def attach_dn_invoice_to_so(
    session: AsyncSession,
    *,
    dn_invoice: Invoice,
    so,
) -> DeliveryNote:
    """Create or refresh DN register row for an uploaded delivery note document."""
    from app.services.sales_match_service import _invoice_qty_and_price

    existing = await dn_linked_to_so(session, dn_invoice.id)
    if existing is not None:
        if existing.sales_order_id != so.id:
            existing.sales_order_id = so.id
        return existing

    loaded = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == dn_invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one_or_none()
    dn_invoice = loaded or dn_invoice
    qty, _, _ = _invoice_qty_and_price(dn_invoice)
    first_line = dn_invoice.line_items[0] if dn_invoice.line_items else None
    from app.services.uom_conversion_service import infer_uom_from_description

    dn_uom = getattr(so, "so_uom", None)
    if first_line:
        dn_uom = getattr(first_line, "uom", None) or infer_uom_from_description(
            first_line.description
        ) or dn_uom

    dn = DeliveryNote(
        tenant_id=so.tenant_id,
        sales_order_id=so.id,
        dn_qty=qty,
        dn_uom=dn_uom,
        dn_currency=getattr(dn_invoice, "currency", None) or "AUD",
        dn_date=dn_invoice.invoice_date,
        shipper=None,
        condition_note="Linked via invoice_no bridge",
        dn_invoice_id=dn_invoice.id,
    )
    session.add(dn)
    await session.flush()
    return dn


async def bridge_orphan_dns_via_commercial_invoice(
    session: AsyncSession,
    *,
    commercial: Invoice,
    so,
    config: RuleBookConfigPayload | None = None,
) -> list[Invoice]:
    """Invoice → DN via invoice_no, then DN → SO through the commercial invoice bridge."""
    from app.services.sales_coding_service import inherit_so_coding_to_invoice

    linked: list[Invoice] = []
    candidates = await find_dn_invoices_by_invoice_no(
        session,
        tenant_id=commercial.tenant_id,
        invoice_no=commercial.invoice_no,
        include_linked=False,
    )
    for dn_invoice in candidates:
        await attach_dn_invoice_to_so(session, dn_invoice=dn_invoice, so=so)
        inherit_so_coding_to_invoice(so, dn_invoice, config=config)
        linked.append(dn_invoice)
    return linked


def dn_has_so_ref(invoice: Invoice) -> bool:
    return is_plausible_so_reference(so_ref_for_invoice(invoice))
