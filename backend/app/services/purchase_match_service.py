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
    MatchAmountLine,
    ThreeWayMatchDisplay,
    ThreeWayMatchResult,
)
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.schemas.uom_conversion import PurchaseMatchConfig
from app.schemas.fx_posting import FxPostingPolicy
from app.services.fx_posting_service import po_invoice_currency_mismatch, resolve_fx_policy
from app.services.uom_conversion_service import (
    convert_qty_to_base,
    infer_uom_from_description,
    invoice_base_qty,
    normalize_uom_token,
    qty_over_billing,
    unit_price_per_base,
)
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


def _amount_line(
    *,
    qty: Decimal | float,
    uom: str | None,
    unit_price: Decimal | float | None,
    line_value: Decimal | float | None,
) -> MatchAmountLine:
    return MatchAmountLine(
        qty=_round2(qty),
        uom=(uom or "").strip().upper() or None,
        unit_price=_round2(unit_price) if unit_price is not None else None,
        line_value=_round2(line_value) if line_value is not None else None,
    )


def _conversion_note(
    *,
    label: str,
    doc_qty: Decimal,
    doc_uom: str | None,
    base_qty: Decimal,
    base_uom: str,
) -> str | None:
    src = normalize_uom_token(doc_uom)
    dst = normalize_uom_token(base_uom) or "EA"
    if not src or src == dst:
        return None
    if float(doc_qty) == float(base_qty):
        return None
    return f"{label} {float(doc_qty):g} {src} → {float(base_qty):g} {dst}"


def build_three_way_match_display(
    po: PurchaseOrder,
    inv: Invoice | None,
    match: ThreeWayMatchResult,
    *,
    match_config: PurchaseMatchConfig | None = None,
) -> ThreeWayMatchDisplay:
    cfg = match_config or PurchaseMatchConfig()
    base_uom = normalize_uom_token(cfg.base_uom) or "EA"
    grn = _latest_grn(po)
    vendor = po.vendor or (inv.vendor if inv is not None else None)

    po_uom = getattr(po, "po_uom", None) or infer_uom_from_description(po.item)
    po_qty = Decimal(str(po.po_qty or 0))
    po_unit = Decimal(str(po.po_unit_price or 0))
    po_base_qty = convert_qty_to_base(po_qty, po_uom, vendor=vendor, config=cfg)
    po_unit_base = unit_price_per_base(po_qty, po_unit, po_uom, vendor=vendor, config=cfg)

    po_on_document = _amount_line(
        qty=po_qty,
        uom=po_uom,
        unit_price=po_unit,
        line_value=po_qty * po_unit if po_qty and po_unit else match.po_value,
    )
    po_for_match = _amount_line(
        qty=po_base_qty,
        uom=base_uom,
        unit_price=po_unit_base,
        line_value=match.po_value,
    )

    notes: list[str] = []
    po_note = _conversion_note(
        label="PO",
        doc_qty=po_qty,
        doc_uom=po_uom,
        base_qty=po_base_qty,
        base_uom=base_uom,
    )
    if po_note:
        notes.append(po_note)

    invoice_on_document: MatchAmountLine | None = None
    invoice_for_match: MatchAmountLine | None = None
    inv_unit_base = Decimal("0")
    if inv is not None:
        inv_qty, inv_unit, _ = _invoice_qty_and_price(inv)
        inv_uom = None
        if inv.line_items:
            first = inv.line_items[0]
            inv_uom = getattr(first, "uom", None) or infer_uom_from_description(first.description)
        inv_base_qty = invoice_base_qty(inv, config=cfg)
        inv_unit_base = unit_price_per_base(
            inv_qty, inv_unit, inv_uom, vendor=vendor, config=cfg
        )
        inv_doc_value = inv_qty * inv_unit if inv_qty and inv_unit else Decimal(str(match.invoice_value))
        invoice_on_document = _amount_line(
            qty=inv_qty,
            uom=inv_uom,
            unit_price=inv_unit,
            line_value=inv_doc_value,
        )
        invoice_for_match = _amount_line(
            qty=inv_base_qty,
            uom=base_uom,
            unit_price=inv_unit_base,
            line_value=match.invoice_value,
        )
        inv_note = _conversion_note(
            label="Invoice",
            doc_qty=inv_qty,
            doc_uom=inv_uom,
            base_qty=inv_base_qty,
            base_uom=base_uom,
        )
        if inv_note:
            notes.append(inv_note)

    grn_on_document: MatchAmountLine | None = None
    grn_for_match: MatchAmountLine | None = None
    if grn is not None:
        grn_uom = getattr(grn, "grn_uom", None) or po_uom
        grn_qty = Decimal(str(grn.grn_qty or 0))
        grn_base_qty = convert_qty_to_base(grn_qty, grn_uom, vendor=vendor, config=cfg)
        compare_unit = inv_unit_base if inv is not None and inv_unit_base > 0 else po_unit_base
        grn_on_document = _amount_line(
            qty=grn_qty,
            uom=grn_uom,
            unit_price=None,
            line_value=None,
        )
        grn_for_match = _amount_line(
            qty=grn_base_qty,
            uom=base_uom,
            unit_price=compare_unit,
            line_value=_round2(grn_base_qty * compare_unit),
        )
        grn_note = _conversion_note(
            label="GRN",
            doc_qty=grn_qty,
            doc_uom=grn_uom,
            base_qty=grn_base_qty,
            base_uom=base_uom,
        )
        if grn_note:
            notes.append(grn_note)

    explanation: str | None = None
    if notes:
        explanation = (
            f"Variance uses all legs normalized to {base_uom}. "
            + " ".join(notes)
            + "."
        )
    elif inv is not None and grn is not None:
        explanation = (
            f"Document units differ, but all three legs reconcile to "
            f"{base_uom} at {match.po_value:,.2f} before GST."
        )

    return ThreeWayMatchDisplay(
        base_uom=base_uom,
        po_on_document=po_on_document,
        po_for_match=po_for_match,
        grn_on_document=grn_on_document,
        grn_for_match=grn_for_match,
        invoice_on_document=invoice_on_document,
        invoice_for_match=invoice_for_match,
        match_explanation=explanation,
    )


def _attach_match_display(
    po: PurchaseOrder,
    inv: Invoice | None,
    match: ThreeWayMatchResult,
    *,
    match_config: PurchaseMatchConfig | None = None,
) -> ThreeWayMatchResult:
    display = build_three_way_match_display(po, inv, match, match_config=match_config)
    return match.model_copy(update={"display": display})


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
    *,
    match_config: PurchaseMatchConfig | None = None,
    qty_tolerance_pct: float | None = None,
    fx_policy: FxPostingPolicy | None = None,
    rule_book_config: RuleBookConfigPayload | None = None,
) -> ThreeWayMatchResult:
    cfg = match_config or PurchaseMatchConfig()
    tolerance = cfg.qty_tolerance_pct if qty_tolerance_pct is None else qty_tolerance_pct
    grn = _latest_grn(po)
    vendor = po.vendor or (inv.vendor if inv is not None else None)
    po_uom = getattr(po, "po_uom", None) or infer_uom_from_description(po.item)
    po_base_qty = convert_qty_to_base(
        po.po_qty, po_uom, vendor=vendor, sku=None, config=cfg
    )
    po_unit_base = unit_price_per_base(
        po.po_qty, po.po_unit_price, po_uom, vendor=vendor, config=cfg
    )
    po_value = _round2(po_base_qty * po_unit_base)

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

    fx = fx_policy
    if fx is None and rule_book_config is not None:
        fx = resolve_fx_policy(
            config=rule_book_config,
            document_type_code=inv.document_type_code,
        )
    if fx is not None and po_invoice_currency_mismatch(
        getattr(po, "po_currency", None),
        inv.currency,
        policy=fx,
    ):
        inv_qty, inv_unit, gst_rate = _invoice_qty_and_price(inv)
        inv_base_qty = invoice_base_qty(inv, config=cfg)
        inv_uom = None
        if inv.line_items:
            first = inv.line_items[0]
            inv_uom = getattr(first, "uom", None) or infer_uom_from_description(first.description)
        inv_unit_base = unit_price_per_base(
            inv_qty, inv_unit, inv_uom, vendor=vendor, config=cfg
        )
        invoice_value = _round2(inv_base_qty * inv_unit_base)
        invoice_gst = _round2(Decimal(str(invoice_value)) * Decimal(str(gst_rate)))
        invoice_total = _round2(Decimal(str(invoice_value)) + Decimal(str(invoice_gst)))
        return ThreeWayMatchResult(
            status="Currency Mismatch",
            qty_variance_value=0.0,
            price_variance_value=0.0,
            total_deviation=0.0,
            po_value=po_value,
            invoice_value=invoice_value,
            invoice_gst=invoice_gst,
            invoice_total=invoice_total,
        )

    inv_base_qty = invoice_base_qty(inv, config=cfg)
    inv_qty, inv_unit, gst_rate = _invoice_qty_and_price(inv)
    inv_uom = None
    if inv.line_items:
        first = inv.line_items[0]
        inv_uom = getattr(first, "uom", None) or infer_uom_from_description(first.description)
    inv_unit_base = unit_price_per_base(
        inv_qty, inv_unit, inv_uom, vendor=vendor, config=cfg
    )
    invoice_value = _round2(inv_base_qty * inv_unit_base)
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

    grn_uom = getattr(grn, "grn_uom", None) or po_uom
    grn_base_qty = convert_qty_to_base(
        grn.grn_qty, grn_uom, vendor=vendor, config=cfg
    )
    qty_variance = _round2((float(inv_base_qty) - float(grn_base_qty)) * float(inv_unit_base))
    price_variance = _round2((float(inv_unit_base) - float(po_unit_base)) * float(inv_base_qty))
    total_deviation = _round2(qty_variance + price_variance)

    if po.variance_approved:
        status = "3-Way Match"
    elif price_variance != 0:
        status = "Price Variance"
    elif qty_over_billing(inv_base_qty, grn_base_qty, tolerance_pct=tolerance):
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
    match_config: PurchaseMatchConfig | None = None,
    qty_tolerance_pct: float | None = None,
    rule_book_config: RuleBookConfigPayload | None = None,
) -> tuple[str, ThreeWayMatchResult]:
    """Compute match status, persist on PO, and audit when status is new or changed."""
    from sqlalchemy.orm import attributes as orm_attributes

    if "goods_receipts" in orm_attributes.instance_state(po).unloaded:
        await session.refresh(po, attribute_names=["goods_receipts"])

    cfg = match_config
    if cfg is None and rule_book_config is not None:
        cfg = rule_book_config.purchase_match
    fx = None
    if rule_book_config is not None and inv is not None:
        fx = resolve_fx_policy(
            config=rule_book_config,
            document_type_code=inv.document_type_code,
        )

    match = compute_three_way_match(
        po,
        inv,
        match_config=cfg,
        qty_tolerance_pct=qty_tolerance_pct,
        fx_policy=fx,
        rule_book_config=rule_book_config,
    )
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
            tenant_id=po.tenant_id,
            detail=three_way_match_audit_detail(po, match, new_status, inv=inv),
        )
    return new_status, match


def _derive_status(match: ThreeWayMatchResult, po: PurchaseOrder) -> PurchaseOrderStatus:
    if match.status == "3-Way Match":
        return PurchaseOrderStatus.MATCHED
    if match.status == "Routed for Approval":
        return PurchaseOrderStatus.VARIANCE_PENDING
    if match.status in ("Price Variance", "Qty Variance", "Currency Mismatch"):
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
    match_cfg = config.purchase_match if config is not None else None
    fx = resolve_fx_policy(config=config, document_type_code=inv.document_type_code) if config and inv else None
    match = compute_three_way_match(
        po,
        inv,
        match_config=match_cfg,
        fx_policy=fx,
        rule_book_config=config,
    )
    match = _attach_match_display(po, inv, match, match_config=match_cfg)
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
    tenant_id: int,
) -> list[PurchaseOrderResponse]:
    """One register row per purchase-routed invoice; POs without invoices listed once."""
    from app.services.po_reference import is_plausible_po_reference

    rows = (
        await db.execute(
            select(PurchaseOrder)
            .where(PurchaseOrder.tenant_id == tenant_id)
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
                Invoice.tenant_id == tenant_id,
                Invoice.route_target == ROUTE_PURCHASE,
                Invoice.po_reference.isnot(None),
                Invoice.po_reference != "",
            )
            .options(selectinload(Invoice.line_items))
            .order_by(Invoice.created_at.desc())
        )
    ).scalars().all()

    config = await load_classification_config(db, tenant_id)
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
                PurchaseOrder.tenant_id == invoice.tenant_id,
                PurchaseOrder.po_number == po_number,
            )
            .options(selectinload(PurchaseOrder.goods_receipts))
        )
    ).scalar_one_or_none()


async def record_goods_receipt(
    db: AsyncSession,
    tenant_id: int,
    purchase_order_id: int,
    body: GoodsReceiptCreate,
) -> PurchaseOrderResponse:
    po = (
        await db.execute(
            select(PurchaseOrder)
            .where(
                PurchaseOrder.id == purchase_order_id,
                PurchaseOrder.tenant_id == tenant_id,
            )
            .options(selectinload(PurchaseOrder.goods_receipts))
        )
    ).scalar_one_or_none()
    if po is None:
        raise LookupError("Purchase order not found")

    grn = GoodsReceipt(
        tenant_id=po.tenant_id,
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

    config = await load_classification_config(db, tenant_id)
    await persist_three_way_match_audit(
        db,
        po,
        inv,
        invoice_id_for_audit=po.invoice_id,
        rule_book_config=config,
    )
    return purchase_order_to_response(po, inv, config=config)


async def approve_purchase_variance(
    db: AsyncSession,
    tenant_id: int,
    purchase_order_id: int,
) -> PurchaseOrderResponse:
    po = (
        await db.execute(
            select(PurchaseOrder)
            .where(
                PurchaseOrder.id == purchase_order_id,
                PurchaseOrder.tenant_id == tenant_id,
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

    config = await load_classification_config(db, tenant_id)
    await persist_three_way_match_audit(
        db,
        po,
        inv,
        invoice_id_for_audit=po.invoice_id,
        rule_book_config=config,
    )
    return purchase_order_to_response(po, inv, config=config)
