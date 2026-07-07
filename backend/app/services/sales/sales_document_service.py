"""SO-first sales documents: classify SO / DN / commercial invoice and sync."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus, SalesDocumentType
from app.models.sales_order import SalesOrder
from app.services.audit.audit_service import log_event
from app.services.extraction.document_heading_utils import extract_document_heading_signals
from app.services.invoice.invoice_evaluation_service import ROUTE_SALES
from app.services.sales.sales_coding_service import code_so_from_invoice, inherit_so_coding_to_invoice
from app.services.sales.sales_linking_service import (
    attach_dn_invoice_to_so,
    bridge_orphan_dns_via_commercial_invoice,
    dn_has_so_ref,
    so_ref_for_invoice,
)
from app.services.sales.sales_match_service import (
    _invoice_qty_and_price,
    persist_three_way_match_audit,
)
from app.services.sales.so_reference import (
    effective_so_reference,
    ensure_invoice_so_reference,
    extract_so_reference_from_text,
    is_plausible_so_reference,
)
from app.services.rule_book.rule_book_mapper import load_classification_config

EVAL_AWAITING_SO = "awaiting_so"

_DN_TOKEN = re.compile(r"(^|[-_/])dn([-_.]|$)", re.I)
_SO_TOKEN = re.compile(r"(^|[-_/])so([-_.]|$)", re.I)
_INV_TOKEN = re.compile(r"(^|[-_/])(inv|invoice)([-_.]|$)", re.I)


def normalize_sales_document_type(value: str | None) -> str | None:
    if not value:
        return None
    key = value.strip().lower()
    if key in {SalesDocumentType.SO.value, SalesDocumentType.DN.value, SalesDocumentType.INVOICE.value}:
        return key
    return None


def _attachment_suggests_dn(filename: str) -> bool:
    name = filename.lower()
    if _DN_TOKEN.search(name):
        return True
    return any(
        hint in name
        for hint in (
            "delivery_note",
            "delivery-note",
            "dispatch_note",
            "packing_list",
            "packing-list",
            "packing list",
        )
    )


def _attachment_suggests_commercial_invoice(filename: str) -> bool:
    name = filename.lower()
    if _INV_TOKEN.search(name):
        return True
    return "tax_invoice" in name or "tax-invoice" in name


def _attachment_suggests_so(filename: str) -> bool:
    name = filename.lower()
    if _attachment_suggests_dn(name) or _attachment_suggests_commercial_invoice(name):
        return False
    if _SO_TOKEN.search(name):
        return True
    return "sales_order" in name or "sales-order" in name


def _parsed_fields_suggest_commercial_invoice(invoice: Invoice) -> bool:
    invoice_no = (invoice.invoice_no or "").strip()
    if invoice_no:
        upper = invoice_no.upper()
        if upper.startswith("INV") or "INVOICE" in upper:
            return True
        so_number = (invoice.so_reference or "").strip()
        if so_number and upper != so_number.upper():
            return True
    return invoice.due_date is not None


def _parsed_fields_suggest_so(invoice: Invoice) -> bool:
    if _parsed_fields_suggest_commercial_invoice(invoice):
        return False
    so_number = (invoice.so_reference or "").strip()
    if not so_number or not is_plausible_so_reference(so_number):
        return False
    invoice_no = (invoice.invoice_no or "").strip()
    if invoice_no and invoice_no.upper() != so_number.upper():
        return False
    return invoice.due_date is None


def infer_sales_document_type(invoice: Invoice) -> str | None:
    """Classify SO / DN / invoice from attachment name, page heading, and parsed fields."""
    attach = (invoice.email_attachment_name or "").strip()
    document_text = (invoice.document_text or "").strip()

    if attach:
        if _attachment_suggests_dn(attach):
            return SalesDocumentType.DN.value
        if _attachment_suggests_commercial_invoice(attach):
            return SalesDocumentType.INVOICE.value
        if _attachment_suggests_so(attach):
            return SalesDocumentType.SO.value

    if document_text:
        heading = extract_document_heading_signals(document_text)
        if "packing_list" in heading.kinds:
            return SalesDocumentType.DN.value
        if heading.has_heading_grn:
            return SalesDocumentType.DN.value
        if heading.has_heading_so:
            return SalesDocumentType.SO.value
        if heading.has_heading_invoice:
            return SalesDocumentType.INVOICE.value

    if _parsed_fields_suggest_commercial_invoice(invoice):
        return SalesDocumentType.INVOICE.value
    if _parsed_fields_suggest_so(invoice):
        return SalesDocumentType.SO.value

    so_number = (invoice.so_reference or "").strip()
    if not invoice.so_reference and document_text:
        extracted = extract_so_reference_from_text(document_text)
        if extracted:
            invoice.so_reference = extracted
            so_number = extracted
    if so_number and is_plausible_so_reference(so_number) and not (invoice.invoice_no or "").strip():
        return SalesDocumentType.SO.value

    return None


def resolve_sales_document_type(
    invoice: Invoice,
    *,
    explicit: str | None = None,
) -> str | None:
    normalized = normalize_sales_document_type(explicit)
    if normalized:
        return normalized
    stored = normalize_sales_document_type(invoice.sales_document_type)
    if stored:
        return stored
    if invoice.route_target != ROUTE_SALES:
        return None
    return infer_sales_document_type(invoice)


def is_commercial_sales_invoice(invoice: Invoice) -> bool:
    doc_type = normalize_sales_document_type(invoice.sales_document_type)
    return doc_type in (None, SalesDocumentType.INVOICE.value)


async def _load_invoice_with_lines(db: AsyncSession, invoice: Invoice) -> Invoice:
    loaded = (
        await db.execute(
            select(Invoice)
            .where(Invoice.id == invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one_or_none()
    return loaded or invoice


async def _get_or_load_so(
    db: AsyncSession,
    invoice: Invoice,
    so_number: str,
) -> SalesOrder | None:
    return (
        await db.execute(
            select(SalesOrder)
            .where(
                SalesOrder.tenant_id == invoice.tenant_id,
                SalesOrder.so_number == so_number,
            )
            .options(selectinload(SalesOrder.delivery_notes))
        )
    ).scalar_one_or_none()


async def _create_or_update_so_from_invoice(
    db: AsyncSession,
    invoice: Invoice,
    so_number: str,
    *,
    so_document_id: int | None = None,
) -> tuple[SalesOrder, bool]:
    """Create or update a sales order row from invoice line data. Returns (so, created)."""
    invoice = await _load_invoice_with_lines(db, invoice)
    qty, unit, _ = _invoice_qty_and_price(invoice)
    first_line = invoice.line_items[0] if invoice.line_items else None

    so = await _get_or_load_so(db, invoice, so_number)
    created = so is None
    if so is None:
        so = SalesOrder(
            tenant_id=invoice.tenant_id,
            so_number=so_number,
            customer=invoice.vendor,
            so_date=invoice.invoice_date,
            item=first_line.description if first_line else None,
            so_qty=qty,
            so_unit_price=unit,
            so_currency=invoice.currency,
            so_document_id=so_document_id,
        )
        db.add(so)
        await db.flush()
        so = (
            await db.execute(
                select(SalesOrder)
                .where(SalesOrder.id == so.id)
                .options(selectinload(SalesOrder.delivery_notes))
            )
        ).scalar_one()
    else:
        if so_document_id is not None:
            so.so_document_id = so_document_id
        if not so.customer:
            so.customer = invoice.vendor
        if so.so_qty <= 0:
            so.so_qty = qty
        if so.so_unit_price <= 0:
            so.so_unit_price = unit
        if not so.so_currency and invoice.currency:
            so.so_currency = invoice.currency

    config = await load_classification_config(db, invoice.tenant_id)
    if not so.ledger:
        code_so_from_invoice(so, invoice, config)
    inherit_so_coding_to_invoice(so, invoice, config=config)
    return so, created


async def _sync_so_document(db: AsyncSession, invoice: Invoice, so_number: str) -> SalesOrder:
    so, _created = await _create_or_update_so_from_invoice(
        db, invoice, so_number, so_document_id=invoice.id
    )
    config = await load_classification_config(db, invoice.tenant_id)

    commercial: Invoice | None = None
    if so.invoice_id:
        commercial = (
            await db.execute(
                select(Invoice)
                .where(Invoice.id == so.invoice_id)
                .options(selectinload(Invoice.line_items))
            )
        ).scalar_one_or_none()
    new_status, match = await persist_three_way_match_audit(
        db,
        so,
        commercial,
        invoice_id_for_audit=invoice.id,
        audit_on_sync=True,
        rule_book_config=config,
    )
    await db.flush()
    await log_event(
        db,
        "sales_so_document_synced",
        invoice_id=invoice.id,
        detail={
            "so_number": so_number,
            "sales_order_id": so.id,
            "three_way_status": new_status,
            "match_status": match.status,
        },
    )
    return so


async def _sync_dn_document(db: AsyncSession, invoice: Invoice, so_number: str) -> SalesOrder | None:
    so, created = await _create_or_update_so_from_invoice(db, invoice, so_number)
    if created:
        await log_event(
            db,
            "sales_so_auto_registered",
            invoice_id=invoice.id,
            detail={
                "so_number": so_number,
                "sales_order_id": so.id,
                "source": "dn",
            },
        )
    if invoice.evaluation_status == EVAL_AWAITING_SO:
        invoice.evaluation_status = None

    invoice = await _load_invoice_with_lines(db, invoice)
    await attach_dn_invoice_to_so(db, dn_invoice=invoice, so=so)
    config = await load_classification_config(db, invoice.tenant_id)
    inherit_so_coding_to_invoice(so, invoice, config=config)

    commercial: Invoice | None = None
    if so.invoice_id:
        commercial = (
            await db.execute(
                select(Invoice)
                .where(Invoice.id == so.invoice_id)
                .options(selectinload(Invoice.line_items))
            )
        ).scalar_one_or_none()
    new_status, match = await persist_three_way_match_audit(
        db,
        so,
        commercial,
        invoice_id_for_audit=invoice.id,
        audit_on_sync=True,
        rule_book_config=config,
    )
    await db.flush()
    await log_event(
        db,
        "sales_dn_document_synced",
        invoice_id=invoice.id,
        detail={
            "so_number": so_number,
            "sales_order_id": so.id,
            "three_way_status": new_status,
            "match_status": match.status,
            "link_mode": "so_ref",
        },
    )
    return so


async def _sync_orphan_dn_document(db: AsyncSession, invoice: Invoice) -> None:
    """DN without so_ref — wait for commercial invoice to bridge via invoice_no."""
    invoice = await _load_invoice_with_lines(db, invoice)
    await log_event(
        db,
        "sales_dn_unlinked",
        invoice_id=invoice.id,
        detail={
            "document_type": SalesDocumentType.DN.value,
            "invoice_no": invoice.invoice_no,
            "reason": "No SO reference on DN — will link when matching invoice arrives",
        },
    )
    await db.flush()


async def _sync_commercial_invoice(db: AsyncSession, invoice: Invoice, so_number: str) -> SalesOrder | None:
    so, created = await _create_or_update_so_from_invoice(db, invoice, so_number)
    if created:
        await log_event(
            db,
            "sales_so_auto_registered",
            invoice_id=invoice.id,
            detail={
                "so_number": so_number,
                "sales_order_id": so.id,
                "source": "commercial_invoice",
            },
        )
    if invoice.evaluation_status == EVAL_AWAITING_SO:
        invoice.evaluation_status = None

    invoice = await _load_invoice_with_lines(db, invoice)
    so.invoice_id = invoice.id
    config = await load_classification_config(db, invoice.tenant_id)
    inherit_so_coding_to_invoice(so, invoice, config=config)

    bridged = await bridge_orphan_dns_via_commercial_invoice(
        db, commercial=invoice, so=so, config=config,
    )
    if bridged:
        await db.refresh(so, attribute_names=["delivery_notes"])

    new_status, match = await persist_three_way_match_audit(
        db,
        so,
        invoice,
        invoice_id_for_audit=invoice.id,
        audit_on_sync=True,
        rule_book_config=config,
    )
    await db.flush()
    await log_event(
        db,
        "sales_invoice_document_synced",
        invoice_id=invoice.id,
        detail={
            "so_number": so_number,
            "sales_order_id": so.id,
            "three_way_status": new_status,
            "match_status": match.status,
            "bridged_dn_invoice_ids": [row.id for row in bridged],
        },
    )
    return so


async def sync_sales_document(
    db: AsyncSession,
    invoice: Invoice,
    *,
    explicit_document_type: str | None = None,
) -> SalesOrder | None:
    """SO-first sync: SO doc creates SO; DN/invoice auto-register SO when ref is plausible."""
    if invoice.route_target != ROUTE_SALES:
        return None

    ensure_invoice_so_reference(invoice)
    await db.flush()

    doc_type = resolve_sales_document_type(invoice, explicit=explicit_document_type)
    if doc_type:
        invoice.sales_document_type = doc_type
        invoice.purchase_document_type = None
        await db.flush()

    so_number = so_ref_for_invoice(invoice)
    if not so_number and invoice.so_reference:
        so_number = effective_so_reference(invoice.so_reference)

    if doc_type == SalesDocumentType.SO.value:
        if not so_number:
            return None
        result = await _sync_so_document(db, invoice, so_number)
        if result is not None:
            from app.services.dossier.dossier_reprocess_service import (
                reprocess_held_commercial_invoices_on_anchor,
            )

            await reprocess_held_commercial_invoices_on_anchor(
                db,
                tenant_id=invoice.tenant_id,
                route_target=ROUTE_SALES,
                anchor_ref=so_number,
                triggering_invoice_id=invoice.id,
            )
        return result
    if doc_type == SalesDocumentType.DN.value:
        if dn_has_so_ref(invoice) and so_number:
            result = await _sync_dn_document(db, invoice, so_number)
            if result is not None:
                from app.services.dossier.dossier_reprocess_service import (
                    reprocess_held_commercial_invoices_on_anchor,
                )

                await reprocess_held_commercial_invoices_on_anchor(
                    db,
                    tenant_id=invoice.tenant_id,
                    route_target=ROUTE_SALES,
                    anchor_ref=so_number,
                    triggering_invoice_id=invoice.id,
                )
            return result
        await _sync_orphan_dn_document(db, invoice)
        return None
    if doc_type == SalesDocumentType.INVOICE.value:
        if not so_number:
            return None
        return await _sync_commercial_invoice(db, invoice, so_number)

    if not so_number:
        return None
    return await _sync_commercial_invoice(db, invoice, so_number)


async def apply_sales_document_type_after_eval(
    db: AsyncSession,
    invoice: Invoice,
) -> None:
    """Set sales_document_type from attachment/heading/parsed signals when not already set."""
    if normalize_sales_document_type(invoice.sales_document_type):
        return
    inferred = infer_sales_document_type(invoice)
    if inferred:
        invoice.sales_document_type = inferred
        await db.flush()
