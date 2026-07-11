"""PO register vendor normalization and touchless vendor-master provisioning."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice
from app.models.purchase_order import PurchaseOrder
from app.schemas.master_data import VendorMasterCreate
from app.services.master_data.master_data_service import create_vendor_master, list_vendor_masters
from app.services.master_data.vendor_detection import find_matching_vendor_master
from app.services.master_data.vendor_name_utils import normalize_vendor_name


def plausible_register_vendor(value: str | None) -> str | None:
    return normalize_vendor_name(value)


async def repair_po_vendor_from_cluster(
    session: AsyncSession,
    po: PurchaseOrder,
) -> bool:
    """Replace implausible PO register vendor with a plausible name from linked documents."""
    if plausible_register_vendor(po.vendor):
        return False

    candidate_ids: list[int] = []
    if po.po_document_id:
        candidate_ids.append(po.po_document_id)
    if po.invoice_id:
        candidate_ids.append(po.invoice_id)

    grn_rows = (
        await session.execute(
            select(Invoice.id).where(
                Invoice.tenant_id == po.tenant_id,
                Invoice.purchase_document_type == "grn",
                Invoice.po_reference == po.po_number,
            )
        )
    ).scalars().all()
    candidate_ids.extend(grn_rows)

    seen: set[int] = set()
    for invoice_id in candidate_ids:
        if invoice_id in seen:
            continue
        seen.add(invoice_id)
        inv = await session.get(Invoice, invoice_id)
        if inv is None:
            continue
        normalized = plausible_register_vendor(inv.vendor)
        if normalized:
            po.vendor = normalized
            return True
    return False


async def ensure_vendor_master_for_po_register(
    session: AsyncSession,
    tenant_id,
    po: PurchaseOrder,
) -> bool:
    """Create a registered vendor master when a PO cluster has a plausible supplier name."""
    await repair_po_vendor_from_cluster(session, po)
    vendor = plausible_register_vendor(po.vendor)
    if not vendor:
        return False

    masters = await list_vendor_masters(session, tenant_id)
    if find_matching_vendor_master(vendor, None, masters):
        return False

    await create_vendor_master(
        session,
        tenant_id,
        VendorMasterCreate(
            name=vendor,
            status="Registered",
        ),
    )
    return True


async def apply_plausible_vendor_to_invoice_from_po(
    session: AsyncSession,
    invoice: Invoice,
    po: PurchaseOrder,
) -> None:
    """When commercial invoice OCR mislabels vendor, inherit PO register supplier."""
    if plausible_register_vendor(invoice.vendor):
        return
    po_vendor = plausible_register_vendor(po.vendor)
    if po_vendor:
        invoice.vendor = po_vendor
