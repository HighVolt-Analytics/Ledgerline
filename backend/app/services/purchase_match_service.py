"""Three-way match for purchase orders, goods receipts, and invoices."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice, InvoiceStatus
from app.models.purchase_order import PurchaseOrder, PurchaseOrderStatus
from app.schemas.purchase import (
    GoodsReceiptCreate,
    PurchaseOrderResponse,
    ThreeWayMatchResult,
)
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.invoice_evaluation_service import ROUTE_PURCHASE, parse_matched_rule_ids
from app.services.purchase_coding_service import (
    code_po_from_invoice,
    inherit_po_coding_to_invoice,
)
from app.services.audit_detail_helpers import (
    compute_three_way_audit_status,
    three_way_match_audit_detail,
)
from app.services.audit_service import log_event
from app.services.rule_book_mapper import load_classification_config, resolve_config_mapping

ROUTE_PURCHASE_MANAGEMENT = ROUTE_PURCHASE


def _round2(value: Decimal | float) -> float:
    return round(float(value), 2)


def _invoice_qty_and_price(inv: Invoice) -> tuple[Decimal, Decimal, float]:
    qty = Decimal("0")
    for line in inv.line_items:
        if line.qty is not None:
            qty += line.qty
    if qty <= 0:
        qty = Decimal("1")
    subtotal = inv.subtotal or Decimal("0")
    unit_price = subtotal / qty if qty else Decimal("0")
    gst_rate = 0.1
    if subtotal and inv.gst:
        gst_rate = float(inv.gst / subtotal)
    return qty, unit_price, gst_rate


def _latest_grn(po: PurchaseOrder) -> GoodsReceipt | None:
    if not po.goods_receipts:
        return None
    return max(po.goods_receipts, key=lambda row: row.id)


def compute_three_way_match(
    po: PurchaseOrder,
    inv: Invoice | None,
) -> ThreeWayMatchResult:
    grn = _latest_grn(po)
    po_qty = float(po.po_qty)
    po_unit = float(po.po_unit_price)
    po_value = _round2(Decimal(str(po_qty)) * Decimal(str(po_unit)))

    if inv is None:
        return ThreeWayMatchResult(
            status="No GRN" if grn is None else "Qty Variance",
            qty_variance_value=0.0,
            price_variance_value=0.0,
            total_deviation=0.0,
            po_value=po_value,
            invoice_value=0.0,
            invoice_gst=0.0,
            invoice_total=0.0,
        )

    inv_qty, inv_unit, gst_rate = _invoice_qty_and_price(inv)
    invoice_value = _round2(inv_qty * inv_unit)
    invoice_gst = _round2(Decimal(str(invoice_value)) * Decimal(str(gst_rate)))
    invoice_total = _round2(Decimal(str(invoice_value)) + Decimal(str(invoice_gst)))

    if grn is None:
        return ThreeWayMatchResult(
            status="No GRN",
            qty_variance_value=0.0,
            price_variance_value=0.0,
            total_deviation=0.0,
            po_value=po_value,
            invoice_value=invoice_value,
            invoice_gst=invoice_gst,
            invoice_total=invoice_total,
        )

    grn_qty = float(grn.grn_qty)
    inv_qty_f = float(inv_qty)
    inv_unit_f = float(inv_unit)
    qty_variance = _round2((inv_qty_f - grn_qty) * inv_unit_f)
    price_variance = _round2((inv_unit_f - po_unit) * inv_qty_f)
    total_deviation = _round2(qty_variance + price_variance)

    if po.variance_approved:
        status = "3-Way Match"
    elif price_variance != 0:
        status = "Price Variance"
    elif inv_qty_f > grn_qty:
        status = "Qty Variance"
    else:
        status = "3-Way Match"

    return ThreeWayMatchResult(
        status=status,
        qty_variance_value=qty_variance,
        price_variance_value=price_variance,
        total_deviation=total_deviation,
        po_value=po_value,
        invoice_value=invoice_value,
        invoice_gst=invoice_gst,
        invoice_total=invoice_total,
    )


async def persist_three_way_match_audit(
    session: AsyncSession,
    po: PurchaseOrder,
    inv: Invoice | None,
    *,
    invoice_id_for_audit: int | None = None,
    audit_on_sync: bool = False,
) -> tuple[str, ThreeWayMatchResult]:
    """Compute match status, persist on PO, and audit when status is new or changed."""
    from sqlalchemy.orm import attributes as orm_attributes

    if "goods_receipts" in orm_attributes.instance_state(po).unloaded:
        await session.refresh(po, attribute_names=["goods_receipts"])

    match = compute_three_way_match(po, inv)
    new_status = compute_three_way_audit_status(po, match)
    previous = po.three_way_match_status
    po.three_way_match_status = new_status
    po.status = _derive_status(match, po)
    audit_invoice_id = invoice_id_for_audit or po.invoice_id or po.po_document_id
    if new_status != previous or audit_on_sync:
        await log_event(
            session,
            "three_way_match_evaluated",
            invoice_id=audit_invoice_id,
            org_id=po.org_id,
            detail=three_way_match_audit_detail(po, match, new_status),
        )
    return new_status, match


def _derive_status(match: ThreeWayMatchResult, po: PurchaseOrder) -> PurchaseOrderStatus:
    if match.status == "3-Way Match":
        return PurchaseOrderStatus.MATCHED
    if match.status == "Routed for Approval":
        return PurchaseOrderStatus.VARIANCE_PENDING
    if match.status in ("Price Variance", "Qty Variance"):
        return PurchaseOrderStatus.VARIANCE_PENDING
    if match.status == "No GRN":
        return PurchaseOrderStatus.OPEN
    return PurchaseOrderStatus.OPEN


def _purchase_rule_from_ids(
    matched_rule_ids: list[str],
    config: RuleBookConfigPayload | None,
) -> tuple[str | None, str | None]:
    if config is None:
        return None, None
    for rid in matched_rule_ids:
        if not rid.startswith("purchase:"):
            continue
        rule_id = rid.split(":", 1)[1]
        for rule in config.purchase_rules:
            if rule.id == rule_id:
                return rule.name, rule.post_to.ledger
    return None, None


def purchase_order_to_response(
    po: PurchaseOrder,
    inv: Invoice | None,
    *,
    config: RuleBookConfigPayload | None = None,
) -> PurchaseOrderResponse:
    grn = _latest_grn(po)
    match = compute_three_way_match(po, inv)
    inv_qty, inv_unit, gst_rate = (Decimal("0"), Decimal("0"), 0.1)
    matched_rule_ids: list[str] = []
    route_target: str | None = None
    evaluation_status: str | None = None
    matched_gl: str | None = None
    matched_rule_name: str | None = None

    if inv is not None:
        inv_qty, inv_unit, gst_rate = _invoice_qty_and_price(inv)
        matched_rule_ids = parse_matched_rule_ids(inv.matched_rule_ids)
        route_target = inv.route_target
        evaluation_status = inv.evaluation_status
        if config is not None:
            matched_rule_name, matched_gl = _purchase_rule_from_ids(matched_rule_ids, config)
            if matched_gl is None and po.ledger:
                matched_gl = po.ledger
            if matched_gl is None:
                hit = resolve_config_mapping(inv, config, purchase_order=po)
                matched_gl = hit.mapping.expense_category
                if matched_rule_name is None and hit.rule_type == "Purchase rule":
                    prefix = "Purchase rule: "
                    if hit.match_reason.startswith(prefix):
                        matched_rule_name = hit.match_reason[len(prefix) :]
    elif po.ledger:
        matched_gl = po.ledger

    return PurchaseOrderResponse(
        id=po.id,
        po_number=po.po_number,
        vendor=inv.vendor if inv is not None and inv.vendor else po.vendor,
        po_date=po.po_date,
        item=po.item,
        requestor=po.requestor,
        po_qty=float(po.po_qty),
        po_unit_price=float(po.po_unit_price),
        grn_qty=float(grn.grn_qty) if grn else None,
        grn_date=grn.grn_date if grn else None,
        grn_receiver=grn.receiver if grn else None,
        grn_condition=grn.condition_note if grn else None,
        invoice_id=inv.id if inv is not None else po.invoice_id,
        po_document_id=po.po_document_id,
        grn_document_id=grn.grn_invoice_id if grn else None,
        invoice_no=inv.invoice_no if inv else None,
        invoice_qty=float(inv_qty),
        invoice_unit_price=float(inv_unit),
        gst_rate=gst_rate,
        variance_approved=po.variance_approved,
        status=po.status.value,
        three_way_match_status=po.three_way_match_status,
        match=match,
        route_target=route_target,
        evaluation_status=evaluation_status,
        matched_rule_ids=matched_rule_ids,
        matched_rule_name=matched_rule_name,
        matched_gl=matched_gl or po.ledger,
        ledger=po.ledger,
        sub_ledger=po.sub_ledger,
        purchase_rule_id=po.purchase_rule_id,
    )


async def list_purchase_orders(
    db: AsyncSession,
    org_id: int,
) -> list[PurchaseOrderResponse]:
    """One register row per purchase-routed invoice; POs without invoices listed once."""
    from app.services.po_reference import is_plausible_po_reference

    rows = (
        await db.execute(
            select(PurchaseOrder)
            .where(PurchaseOrder.org_id == org_id)
            .options(
                selectinload(PurchaseOrder.goods_receipts),
            )
            .order_by(PurchaseOrder.created_at.desc())
        )
    ).scalars().all()
    po_by_number = {po.po_number: po for po in rows}

    routed_invoices = (
        await db.execute(
            select(Invoice)
            .where(
                Invoice.org_id == org_id,
                Invoice.route_target == ROUTE_PURCHASE,
                Invoice.po_reference.isnot(None),
                Invoice.po_reference != "",
            )
            .options(selectinload(Invoice.line_items))
            .order_by(Invoice.created_at.desc())
        )
    ).scalars().all()

    config = load_classification_config(org_id)
    responses: list[PurchaseOrderResponse] = []
    seen_pairs: set[tuple[int, int]] = set()
    pos_with_rows: set[int] = set()

    for inv in routed_invoices:
        if inv.purchase_document_type in ("po", "grn"):
            continue
        po_number = (inv.po_reference or "").strip()
        if not is_plausible_po_reference(po_number):
            continue
        po = po_by_number.get(po_number)
        if po is None:
            continue
        key = (po.id, inv.id)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        pos_with_rows.add(po.id)
        responses.append(purchase_order_to_response(po, inv, config=config))

    for po in rows:
        if po.id in pos_with_rows:
            continue
        inv = None
        if po.invoice_id:
            inv = (
                await db.execute(
                    select(Invoice)
                    .where(Invoice.id == po.invoice_id)
                    .options(selectinload(Invoice.line_items))
                )
            ).scalar_one_or_none()
        responses.append(purchase_order_to_response(po, inv, config=config))

    return responses


async def sync_purchase_order_from_invoice(
    db: AsyncSession,
    invoice: Invoice,
) -> PurchaseOrder | None:
    """Backward-compatible alias for PO-first purchase document sync."""
    from app.services.purchase_document_service import sync_purchase_document

    return await sync_purchase_document(db, invoice)


async def load_purchase_order_for_invoice(
    db: AsyncSession,
    invoice: Invoice,
) -> PurchaseOrder | None:
    from app.services.po_reference import is_plausible_po_reference

    po_number = (invoice.po_reference or "").strip()
    if not po_number or not is_plausible_po_reference(po_number):
        return None
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


async def record_goods_receipt(
    db: AsyncSession,
    org_id: int,
    purchase_order_id: int,
    body: GoodsReceiptCreate,
) -> PurchaseOrderResponse:
    po = (
        await db.execute(
            select(PurchaseOrder)
            .where(
                PurchaseOrder.id == purchase_order_id,
                PurchaseOrder.org_id == org_id,
            )
            .options(selectinload(PurchaseOrder.goods_receipts))
        )
    ).scalar_one_or_none()
    if po is None:
        raise LookupError("Purchase order not found")

    grn = GoodsReceipt(
        purchase_order_id=po.id,
        grn_qty=body.grn_qty,
        grn_date=body.grn_date or date.today(),
        receiver=body.receiver,
        condition_note=body.condition_note,
    )
    db.add(grn)
    await db.flush()
    await db.refresh(po, attribute_names=["goods_receipts"])

    inv: Invoice | None = None
    if po.invoice_id:
        inv = (
            await db.execute(
                select(Invoice)
                .where(Invoice.id == po.invoice_id)
                .options(selectinload(Invoice.line_items))
            )
        ).scalar_one_or_none()

    await persist_three_way_match_audit(db, po, inv, invoice_id_for_audit=po.invoice_id)
    config = load_classification_config(org_id)
    return purchase_order_to_response(po, inv, config=config)


async def approve_purchase_variance(
    db: AsyncSession,
    org_id: int,
    purchase_order_id: int,
) -> PurchaseOrderResponse:
    po = (
        await db.execute(
            select(PurchaseOrder)
            .where(
                PurchaseOrder.id == purchase_order_id,
                PurchaseOrder.org_id == org_id,
            )
            .options(selectinload(PurchaseOrder.goods_receipts))
        )
    ).scalar_one_or_none()
    if po is None:
        raise LookupError("Purchase order not found")

    po.variance_approved = True
    inv: Invoice | None = None
    if po.invoice_id:
        inv = (
            await db.execute(
                select(Invoice)
                .where(Invoice.id == po.invoice_id)
                .options(selectinload(Invoice.line_items))
            )
        ).scalar_one_or_none()

    await persist_three_way_match_audit(db, po, inv, invoice_id_for_audit=po.invoice_id)
    config = load_classification_config(org_id)
    return purchase_order_to_response(po, inv, config=config)
