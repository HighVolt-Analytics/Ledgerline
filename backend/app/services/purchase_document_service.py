"""PO-first purchase documents: classify PO / GRN / commercial invoice and sync."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice, InvoiceStatus, PurchaseDocumentType
from app.models.purchase_order import PurchaseOrder
from app.services.audit_service import log_event
from app.services.bundle_vendor_service import reconcile_dossier_vendor
from app.services.invoice_evaluation_service import ROUTE_PURCHASE
from app.services.document_heading_utils import extract_document_heading_signals
from app.services.po_reference import (
    effective_po_reference,
    extract_po_reference_from_text,
    is_plausible_po_reference,
)
from app.services.purchase_coding_service import code_po_from_invoice, inherit_po_coding_to_invoice
from app.services.purchase_match_service import (
    _invoice_qty_and_price,
    load_purchase_order_for_invoice,
    persist_three_way_match_audit,
)
from app.services.rule_book_mapper import load_classification_config

EVAL_AWAITING_PO = "awaiting_po"

_GRN_TOKEN = re.compile(r"(^|[-_/])grn([-_.]|$)", re.I)
_PO_TOKEN = re.compile(r"(^|[-_/])po([-_.]|$)", re.I)
_INV_TOKEN = re.compile(r"(^|[-_/])(inv|invoice)([-_.]|$)", re.I)


def normalize_purchase_document_type(value: str | None) -> str | None:
    if not value:
        return None
    key = value.strip().lower()
    if key in {PurchaseDocumentType.PO.value, PurchaseDocumentType.GRN.value, PurchaseDocumentType.INVOICE.value}:
        return key
    return None


def _attachment_suggests_grn(filename: str) -> bool:
    name = filename.lower()
    if _GRN_TOKEN.search(name):
        return True
    return any(hint in name for hint in ("goods_receipt", "goods-receipt", "delivery_note", "delivery-note"))


def _attachment_suggests_commercial_invoice(filename: str) -> bool:
    name = filename.lower()
    if _INV_TOKEN.search(name):
        return True
    return "tax_invoice" in name or "tax-invoice" in name


def _attachment_suggests_po(filename: str) -> bool:
    name = filename.lower()
    if _attachment_suggests_grn(name) or _attachment_suggests_commercial_invoice(name):
        return False
    if _PO_TOKEN.search(name):
        return True
    return "purchase_order" in name or "purchase-order" in name


def _parsed_fields_suggest_commercial_invoice(invoice: Invoice) -> bool:
    invoice_no = (invoice.invoice_no or "").strip()
    if invoice_no:
        upper = invoice_no.upper()
        if upper.startswith("INV") or "INVOICE" in upper:
            return True
        po_number = (invoice.po_reference or "").strip()
        if po_number and upper != po_number.upper():
            return True
    return invoice.due_date is not None


def _parsed_fields_suggest_po(invoice: Invoice) -> bool:
    if _parsed_fields_suggest_commercial_invoice(invoice):
        return False
    po_number = (invoice.po_reference or "").strip()
    if not po_number or not is_plausible_po_reference(po_number):
        return False
    invoice_no = (invoice.invoice_no or "").strip()
    if invoice_no and invoice_no.upper() != po_number.upper():
        return False
    return invoice.due_date is None


def infer_purchase_document_type(invoice: Invoice) -> str | None:
    """Classify PO / GRN / invoice from attachment name, page heading, and parsed fields."""
    attach = (invoice.email_attachment_name or "").strip()
    document_text = (invoice.document_text or "").strip()

    if attach:
        if _attachment_suggests_grn(attach):
            return PurchaseDocumentType.GRN.value
        if _attachment_suggests_commercial_invoice(attach):
            return PurchaseDocumentType.INVOICE.value
        if _attachment_suggests_po(attach):
            return PurchaseDocumentType.PO.value

    if document_text:
        heading = extract_document_heading_signals(document_text)
        if heading.has_heading_grn:
            return PurchaseDocumentType.GRN.value
        if heading.has_heading_po:
            return PurchaseDocumentType.PO.value
        if heading.has_heading_invoice:
            return PurchaseDocumentType.INVOICE.value

    if _parsed_fields_suggest_commercial_invoice(invoice):
        return PurchaseDocumentType.INVOICE.value
    if _parsed_fields_suggest_po(invoice):
        return PurchaseDocumentType.PO.value

    po_number = (invoice.po_reference or "").strip()
    if po_number and is_plausible_po_reference(po_number) and not (invoice.invoice_no or "").strip():
        return PurchaseDocumentType.PO.value

    return None


def resolve_purchase_document_type(
    invoice: Invoice,
    *,
    explicit: str | None = None,
) -> str | None:
    normalized = normalize_purchase_document_type(explicit)
    if normalized:
        return normalized
    stored = normalize_purchase_document_type(invoice.purchase_document_type)
    if stored:
        return stored
    if invoice.route_target != ROUTE_PURCHASE:
        return None
    return infer_purchase_document_type(invoice)


def is_commercial_purchase_invoice(invoice: Invoice) -> bool:
    doc_type = normalize_purchase_document_type(invoice.purchase_document_type)
    return doc_type in (None, PurchaseDocumentType.INVOICE.value)


async def _load_invoice_with_lines(db: AsyncSession, invoice: Invoice) -> Invoice:
    loaded = (
        await db.execute(
            select(Invoice)
            .where(Invoice.id == invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one_or_none()
    return loaded or invoice


async def _get_or_load_po(
    db: AsyncSession,
    invoice: Invoice,
    po_number: str,
) -> PurchaseOrder | None:
    return (
        await db.execute(
            select(PurchaseOrder)
            .where(
                PurchaseOrder.org_id == invoice.org_id,
                PurchaseOrder.po_number == po_number,
            )
            .options(selectinload(PurchaseOrder.goods_receipts))
        )
    ).scalar_one_or_none()


async def _sync_po_document(db: AsyncSession, invoice: Invoice, po_number: str) -> PurchaseOrder:
    invoice = await _load_invoice_with_lines(db, invoice)
    qty, unit, _ = _invoice_qty_and_price(invoice)
    first_line = invoice.line_items[0] if invoice.line_items else None

    po = await _get_or_load_po(db, invoice, po_number)
    if po is None:
        po = PurchaseOrder(
            org_id=invoice.org_id,
            po_number=po_number,
            vendor=invoice.vendor,
            po_date=invoice.invoice_date,
            item=first_line.description if first_line else None,
            po_qty=qty,
            po_unit_price=unit,
            po_document_id=invoice.id,
        )
        db.add(po)
        await db.flush()
        po = (
            await db.execute(
                select(PurchaseOrder)
                .where(PurchaseOrder.id == po.id)
                .options(selectinload(PurchaseOrder.goods_receipts))
            )
        ).scalar_one()
    else:
        po.po_document_id = invoice.id
        if not po.vendor:
            po.vendor = invoice.vendor
        if po.po_qty <= 0:
            po.po_qty = qty
        if po.po_unit_price <= 0:
            po.po_unit_price = unit

    config = load_classification_config(invoice.org_id)
    if not po.ledger:
        code_po_from_invoice(po, invoice, config)
    inherit_po_coding_to_invoice(po, invoice)

    commercial: Invoice | None = None
    if po.invoice_id:
        commercial = (
            await db.execute(
                select(Invoice)
                .where(Invoice.id == po.invoice_id)
                .options(selectinload(Invoice.line_items))
            )
        ).scalar_one_or_none()
    new_status, match = await persist_three_way_match_audit(
        db,
        po,
        commercial,
        invoice_id_for_audit=invoice.id,
        audit_on_sync=True,
    )
    await db.flush()
    await log_event(
        db,
        "purchase_po_document_synced",
        invoice_id=invoice.id,
        detail={
            "po_number": po_number,
            "purchase_order_id": po.id,
            "three_way_status": new_status,
            "match_status": match.status,
        },
    )
    await reconcile_dossier_vendor(
        db, invoice, po, document_type=PurchaseDocumentType.PO.value
    )
    return po


async def _sync_grn_document(db: AsyncSession, invoice: Invoice, po_number: str) -> PurchaseOrder | None:
    po = await _get_or_load_po(db, invoice, po_number)
    if po is None:
        invoice.evaluation_status = EVAL_AWAITING_PO
        invoice.status = InvoiceStatus.EXCEPTION
        await log_event(
            db,
            "purchase_awaiting_po",
            invoice_id=invoice.id,
            detail={"po_number": po_number, "document_type": PurchaseDocumentType.GRN.value},
        )
        await db.flush()
        return None

    invoice = await _load_invoice_with_lines(db, invoice)
    qty, _, _ = _invoice_qty_and_price(invoice)
    grn = GoodsReceipt(
        purchase_order_id=po.id,
        grn_qty=qty,
        grn_date=invoice.invoice_date or date.today(),
        receiver=None,
        condition_note="From uploaded GRN document",
        grn_invoice_id=invoice.id,
    )
    db.add(grn)
    inherit_po_coding_to_invoice(po, invoice)

    commercial: Invoice | None = None
    if po.invoice_id:
        commercial = (
            await db.execute(
                select(Invoice)
                .where(Invoice.id == po.invoice_id)
                .options(selectinload(Invoice.line_items))
            )
        ).scalar_one_or_none()
    new_status, match = await persist_three_way_match_audit(
        db,
        po,
        commercial,
        invoice_id_for_audit=invoice.id,
        audit_on_sync=True,
    )
    await db.flush()
    await log_event(
        db,
        "purchase_grn_document_synced",
        invoice_id=invoice.id,
        detail={
            "po_number": po_number,
            "purchase_order_id": po.id,
            "three_way_status": new_status,
            "match_status": match.status,
        },
    )
    await reconcile_dossier_vendor(
        db, invoice, po, document_type=PurchaseDocumentType.GRN.value
    )
    return po


async def _sync_commercial_invoice(db: AsyncSession, invoice: Invoice, po_number: str) -> PurchaseOrder | None:
    po = await _get_or_load_po(db, invoice, po_number)
    if po is None:
        invoice.evaluation_status = EVAL_AWAITING_PO
        invoice.status = InvoiceStatus.EXCEPTION
        await log_event(
            db,
            "purchase_awaiting_po",
            invoice_id=invoice.id,
            detail={"po_number": po_number, "document_type": PurchaseDocumentType.INVOICE.value},
        )
        await db.flush()
        return None

    invoice = await _load_invoice_with_lines(db, invoice)
    po.invoice_id = invoice.id
    inherit_po_coding_to_invoice(po, invoice)

    new_status, match = await persist_three_way_match_audit(
        db,
        po,
        invoice,
        invoice_id_for_audit=invoice.id,
        audit_on_sync=True,
    )
    await db.flush()
    await log_event(
        db,
        "purchase_invoice_document_synced",
        invoice_id=invoice.id,
        detail={
            "po_number": po_number,
            "purchase_order_id": po.id,
            "three_way_status": new_status,
            "match_status": match.status,
        },
    )
    await reconcile_dossier_vendor(
        db, invoice, po, document_type=PurchaseDocumentType.INVOICE.value
    )
    return po


async def sync_purchase_document(
    db: AsyncSession,
    invoice: Invoice,
    *,
    explicit_document_type: str | None = None,
) -> PurchaseOrder | None:
    """PO-first sync: PO doc creates PO; GRN/invoice require existing PO."""
    if invoice.route_target != ROUTE_PURCHASE:
        return None

    po_number = (invoice.po_reference or "").strip()
    if not po_number or not is_plausible_po_reference(po_number):
        return None

    doc_type = resolve_purchase_document_type(invoice, explicit=explicit_document_type)
    if doc_type:
        invoice.purchase_document_type = doc_type
        await db.flush()

    if doc_type == PurchaseDocumentType.PO.value:
        return await _sync_po_document(db, invoice, po_number)
    if doc_type == PurchaseDocumentType.GRN.value:
        return await _sync_grn_document(db, invoice, po_number)
    if doc_type == PurchaseDocumentType.INVOICE.value:
        return await _sync_commercial_invoice(db, invoice, po_number)

    return await _sync_commercial_invoice(db, invoice, po_number)


async def apply_purchase_document_type_after_eval(
    db: AsyncSession,
    invoice: Invoice,
) -> None:
    """Set purchase_document_type from attachment/heading/parsed signals when not already set."""
    if normalize_purchase_document_type(invoice.purchase_document_type):
        return
    inferred = infer_purchase_document_type(invoice)
    if inferred:
        invoice.purchase_document_type = inferred
        await db.flush()
