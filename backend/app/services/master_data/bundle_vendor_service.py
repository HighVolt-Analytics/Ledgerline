"""Canonical vendor for a purchase dossier (PO + GRN + invoice on same po_reference)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice, PurchaseDocumentType
from app.models.purchase_order import PurchaseOrder
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.rule_book.rule_book_mapper import load_classification_config
from app.services.master_data.vendor_detection import find_matching_vendor_master, name_signal_matches
from app.services.master_data.vendor_name_utils import is_plausible_vendor_name, normalize_vendor_name
from app.services.master_data.vendor_resolver import match_rule_book_vendor_name


def resolve_canonical_vendor_name(
    tenant_id: int,
    *,
    vendor_names: list[str | None],
    abns: list[str | None] | None = None,
    prefer_name: str | None = None,
    config: RuleBookConfigPayload,
) -> str | None:
    """
    Pick one vendor label for a dossier: vendor master (ABN / fuzzy name) then PO anchor.
    """
    abns = abns or []
    masters = config.vendor_masters

    for abn in abns:
        doc_abn = (abn or "").strip()
        if not doc_abn:
            continue
        master = find_matching_vendor_master(None, doc_abn, masters)
        if master:
            return master.name

    ordered_names: list[str] = []
    if prefer_name and prefer_name.strip():
        ordered_names.append(prefer_name.strip())
    for name in vendor_names:
        cleaned = (name or "").strip()
        if cleaned and cleaned not in ordered_names:
            ordered_names.append(cleaned)

    for name in ordered_names:
        master = find_matching_vendor_master(name, None, masters)
        if master:
            return master.name
        canonical = match_rule_book_vendor_name(name, config=config)
        if canonical:
            return canonical
        normalized = normalize_vendor_name(name)
        if normalized:
            return normalized

    return None


def vendors_align_to_same_master(
    tenant_id: int,
    left_name: str | None,
    left_abn: str | None,
    right_name: str | None,
    right_abn: str | None,
    *,
    config: RuleBookConfigPayload,
) -> bool:
    """True when both sides fuzzy-match the same vendor master (or identical text)."""
    left = (left_name or "").strip()
    right = (right_name or "").strip()
    if left and right and left.lower() == right.lower():
        return True

    masters = config.vendor_masters
    left_master = find_matching_vendor_master(left, left_abn, masters)
    right_master = find_matching_vendor_master(right, right_abn, masters)
    if left_master and right_master:
        return left_master.id == right_master.id
    if left_master and right and name_signal_matches(right, left_master):
        return True
    if right_master and left and name_signal_matches(left, right_master):
        return True
    return False


async def _load_po_with_receipts(
    db: AsyncSession,
    po: PurchaseOrder,
) -> PurchaseOrder:
    loaded = (
        await db.execute(
            select(PurchaseOrder)
            .where(PurchaseOrder.id == po.id)
            .options(selectinload(PurchaseOrder.goods_receipts))
        )
    ).scalar_one_or_none()
    return loaded or po


def _dossier_invoice_ids(po: PurchaseOrder) -> set[int]:
    ids: set[int] = set()
    if po.po_document_id:
        ids.add(po.po_document_id)
    if po.invoice_id:
        ids.add(po.invoice_id)
    for grn in po.goods_receipts:
        if grn.grn_invoice_id:
            ids.add(grn.grn_invoice_id)
    return ids


async def propagate_canonical_vendor(
    db: AsyncSession,
    po: PurchaseOrder,
    canonical_vendor: str,
    *,
    canonical_abn: str | None = None,
) -> list[int]:
    """Write canonical vendor to PO register and every linked bundle invoice."""
    if not canonical_vendor.strip():
        return []

    po = await _load_po_with_receipts(db, po)
    po.vendor = canonical_vendor.strip()
    updated: list[int] = []

    for inv_id in _dossier_invoice_ids(po):
        inv = await db.get(Invoice, inv_id)
        if inv is None or inv.tenant_id != po.tenant_id:
            continue
        inv.vendor = canonical_vendor.strip()
        if canonical_abn and not (inv.abn or "").strip():
            inv.abn = canonical_abn
        updated.append(inv.id)

    await db.flush()
    return updated


async def reconcile_dossier_vendor(
    db: AsyncSession,
    invoice: Invoice,
    po: PurchaseOrder,
    *,
    document_type: str | None,
) -> str | None:
    """
    Resolve and apply one vendor for the whole purchase bundle.

    PO anchors the dossier; GRN inherits; commercial invoice aligns to PO/master.
    """
    doc_type = (document_type or invoice.purchase_document_type or "").strip().lower()
    po_anchor = (po.vendor or "").strip()

    config = await load_classification_config(db, invoice.tenant_id)

    candidate_names: list[str | None] = []
    candidate_abns: list[str | None] = [invoice.abn, None]

    if doc_type == PurchaseDocumentType.PO.value:
        candidate_names = [invoice.vendor, po_anchor or None]
        prefer = invoice.vendor or po_anchor
    elif doc_type == PurchaseDocumentType.GRN.value:
        candidate_names = [po_anchor or None, invoice.vendor]
        prefer = po_anchor or None
    else:
        candidate_names = [po_anchor or None, invoice.vendor]
        prefer = po_anchor or invoice.vendor

    canonical = resolve_canonical_vendor_name(
        invoice.tenant_id,
        vendor_names=candidate_names,
        abns=candidate_abns,
        prefer_name=prefer,
        config=config,
    )
    if not canonical:
        return None

    canonical_abn = (invoice.abn or "").strip() or None
    if not canonical_abn:
        master = find_matching_vendor_master(canonical, None, config.vendor_masters)
        if master and master.abn and master.abn != "PENDING":
            canonical_abn = master.abn

    if doc_type == PurchaseDocumentType.GRN.value:
        invoice.vendor = canonical
    elif doc_type == PurchaseDocumentType.INVOICE.value:
        parsed = (invoice.vendor or "").strip()
        if not parsed or vendors_align_to_same_master(
            invoice.tenant_id, parsed, invoice.abn, canonical, canonical_abn, config=config
        ):
            invoice.vendor = canonical
        elif po_anchor and not vendors_align_to_same_master(
            invoice.tenant_id, parsed, invoice.abn, po_anchor, None, config=config
        ):
            invoice.vendor = canonical
    else:
        invoice.vendor = canonical

    await propagate_canonical_vendor(
        db,
        po,
        canonical,
        canonical_abn=canonical_abn,
    )
    return canonical
