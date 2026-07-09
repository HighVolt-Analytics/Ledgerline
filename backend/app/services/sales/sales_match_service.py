"""Three-way match for sales orders, delivery notes, and invoices."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.delivery_note import DeliveryNote
from app.models.invoice import Invoice, InvoiceStatus
from app.models.sales_order import SalesOrder, SalesOrderStatus
from app.schemas.purchase import MatchAmountLine, ThreeWayMatchDisplay, ThreeWayMatchResult
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.schemas.sales import DeliveryNoteCreate, SalesOrderResponse, TwoWaySalesMatchResponse
from app.schemas.uom_conversion import PurchaseMatchConfig
from app.services.audit.audit_service import log_event
from app.services.invoice.invoice_evaluation_service import ROUTE_SALES, parse_matched_rule_ids
from app.services.rule_book.rule_book_mapper import load_classification_config, resolve_config_mapping
from app.services.sales.sales_coding_service import code_so_from_invoice, inherit_so_coding_to_invoice

ROUTE_SALES_MANAGEMENT = ROUTE_SALES


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


def _qty_over_billing(
    invoice_qty: Decimal,
    received_qty: Decimal,
    *,
    tolerance_pct: float = 0.0,
) -> bool:
    if received_qty <= 0:
        return invoice_qty > 0
    allowed = received_qty * (Decimal("1") + Decimal(str(tolerance_pct)) / Decimal("100"))
    return invoice_qty > allowed


def _latest_dn(so: SalesOrder) -> DeliveryNote | None:
    if not so.delivery_notes:
        return None
    return max(so.delivery_notes, key=lambda row: row.id)


def _invoice_qty_and_price(inv: Invoice) -> tuple[Decimal, Decimal, float]:
    qty = Decimal("0")
    for line in inv.line_items:
        if line.qty is not None:
            qty += line.qty
    if qty <= 0:
        qty = Decimal("1")
    subtotal = inv.subtotal or Decimal("0")
    unit_price = subtotal / qty if qty else Decimal("0")
    from app.services.extraction.gst_rate import invoice_gst_rate_fraction

    gst_rate = invoice_gst_rate_fraction(inv)
    if gst_rate is None:
        gst_rate = 0.0
    return qty, unit_price, gst_rate


def build_three_way_match_display(
    so: SalesOrder,
    inv: Invoice | None,
    match: ThreeWayMatchResult,
) -> ThreeWayMatchDisplay:
    dn = _latest_dn(so)

    so_qty = Decimal(str(so.so_qty or 0))
    so_unit = Decimal(str(so.so_unit_price or 0))
    so_line = _amount_line(
        qty=so_qty,
        uom=getattr(so, "so_uom", None),
        unit_price=so_unit,
        line_value=match.po_value,
    )

    invoice_line: MatchAmountLine | None = None
    if inv is not None:
        inv_qty, inv_unit, _ = _invoice_qty_and_price(inv)
        inv_uom = getattr(inv.line_items[0], "uom", None) if inv.line_items else None
        invoice_line = _amount_line(
            qty=inv_qty,
            uom=inv_uom,
            unit_price=inv_unit,
            line_value=match.invoice_value,
        )

    dn_line: MatchAmountLine | None = None
    if dn is not None:
        dn_qty = Decimal(str(dn.dn_qty or 0))
        dn_line = _amount_line(
            qty=dn_qty,
            uom=getattr(dn, "dn_uom", None),
            unit_price=None,
            line_value=None,
        )

    return ThreeWayMatchDisplay(
        po_on_document=so_line,
        po_for_match=so_line,
        grn_on_document=dn_line,
        grn_for_match=dn_line,
        invoice_on_document=invoice_line,
        invoice_for_match=invoice_line,
    )


def _attach_match_display(
    so: SalesOrder,
    inv: Invoice | None,
    match: ThreeWayMatchResult,
) -> ThreeWayMatchResult:
    display = build_three_way_match_display(so, inv, match)
    return match.model_copy(update={"display": display})


def compute_three_way_match(
    so: SalesOrder,
    inv: Invoice | None,
    *,
    match_config: PurchaseMatchConfig | None = None,
    qty_tolerance_pct: float | None = None,
    rule_book_config: RuleBookConfigPayload | None = None,
) -> ThreeWayMatchResult:
    cfg = match_config or PurchaseMatchConfig()
    tolerance = cfg.qty_tolerance_pct if qty_tolerance_pct is None else qty_tolerance_pct
    dn = _latest_dn(so)

    so_qty = Decimal(str(so.so_qty or 0))
    so_unit = Decimal(str(so.so_unit_price or 0))
    so_value = _round2(so_qty * so_unit)

    if inv is None:
        return ThreeWayMatchResult(
            status="No DN" if dn is None else "Qty Variance",
            qty_variance_value=0.0,
            price_variance_value=0.0,
            total_deviation=0.0,
            po_value=so_value,
            invoice_value=0.0,
            invoice_gst=0.0,
            invoice_total=0.0,
        )

    inv_qty, inv_unit, gst_rate = _invoice_qty_and_price(inv)
    invoice_value = _round2(inv_qty * inv_unit)
    invoice_gst = _round2(Decimal(str(invoice_value)) * Decimal(str(gst_rate)))
    invoice_total = _round2(Decimal(str(invoice_value)) + Decimal(str(invoice_gst)))

    if dn is None:
        return ThreeWayMatchResult(
            status="No DN",
            qty_variance_value=0.0,
            price_variance_value=0.0,
            total_deviation=0.0,
            po_value=so_value,
            invoice_value=invoice_value,
            invoice_gst=invoice_gst,
            invoice_total=invoice_total,
        )

    dn_qty = Decimal(str(dn.dn_qty or 0))
    qty_variance = _round2((float(inv_qty) - float(dn_qty)) * float(inv_unit))
    price_variance = _round2((float(inv_unit) - float(so_unit)) * float(inv_qty))
    total_deviation = _round2(qty_variance + price_variance)

    if so.variance_approved:
        status = "3-Way Match"
    elif price_variance != 0:
        status = "Price Variance"
    elif _qty_over_billing(inv_qty, dn_qty, tolerance_pct=tolerance):
        status = "Qty Variance"
    else:
        status = "3-Way Match"

    return ThreeWayMatchResult(
        status=status,
        qty_variance_value=qty_variance,
        price_variance_value=price_variance,
        total_deviation=total_deviation,
        po_value=so_value,
        invoice_value=invoice_value,
        invoice_gst=invoice_gst,
        invoice_total=invoice_total,
    )


def _compute_three_way_audit_status(so: SalesOrder, match: ThreeWayMatchResult) -> str:
    so_present = so.so_document_id is not None
    dn_present = _latest_dn(so) is not None
    invoice_present = so.invoice_id is not None

    if match.status == "3-Way Match":
        return "full_match"
    if match.status in ("Price Variance", "Qty Variance", "Routed for Approval"):
        if so_present and dn_present and invoice_present:
            return "mismatch"
    if not so_present or not dn_present or not invoice_present:
        return "partial"
    return "partial"


def _three_way_match_audit_detail(
    so: SalesOrder,
    match: ThreeWayMatchResult,
    status: str,
    *,
    inv: Invoice | None = None,
) -> dict[str, object]:
    dn = _latest_dn(so)
    amounts_reconciled = match.status == "3-Way Match"
    inv_qty: float | None = None
    inv_unit: float | None = None
    invoice_no: str | None = None
    currency = "SGD"
    if inv is not None:
        qty, unit, _ = _invoice_qty_and_price(inv)
        inv_qty = float(qty)
        inv_unit = float(unit)
        invoice_no = inv.invoice_no
        currency = (inv.currency or "SGD").strip() or "SGD"
    return {
        "so_present": so.so_document_id is not None,
        "dn_present": dn is not None,
        "invoice_present": so.invoice_id is not None,
        "amounts_reconciled": amounts_reconciled,
        "status": status,
        "match_status": match.status,
        "sales_order_id": so.id,
        "so_number": so.so_number,
        "so_qty": float(so.so_qty),
        "so_unit_price": float(so.so_unit_price),
        "so_value": match.po_value,
        "so_date": so.so_date.isoformat() if so.so_date else None,
        "dn_qty": float(dn.dn_qty) if dn is not None else None,
        "dn_date": dn.dn_date.isoformat() if dn is not None and dn.dn_date else None,
        "dn_shipper": dn.shipper if dn is not None else None,
        "dn_condition": dn.condition_note if dn is not None else None,
        "invoice_no": invoice_no,
        "invoice_qty": inv_qty,
        "invoice_unit_price": inv_unit,
        "invoice_value": match.invoice_value,
        "invoice_gst": match.invoice_gst,
        "invoice_total": match.invoice_total,
        "qty_variance_value": match.qty_variance_value,
        "price_variance_value": match.price_variance_value,
        "total_deviation": match.total_deviation,
        "currency": currency,
    }


async def persist_three_way_match_audit(
    session: AsyncSession,
    so: SalesOrder,
    inv: Invoice | None,
    *,
    invoice_id_for_audit: int | None = None,
    audit_on_sync: bool = False,
    match_config: PurchaseMatchConfig | None = None,
    qty_tolerance_pct: float | None = None,
    rule_book_config: RuleBookConfigPayload | None = None,
) -> tuple[str, ThreeWayMatchResult]:
    from sqlalchemy.orm import attributes as orm_attributes

    if "delivery_notes" in orm_attributes.instance_state(so).unloaded:
        await session.refresh(so, attribute_names=["delivery_notes"])

    cfg = match_config
    if cfg is None and rule_book_config is not None:
        cfg = rule_book_config.purchase_match

    match = compute_three_way_match(
        so,
        inv,
        match_config=cfg,
        qty_tolerance_pct=qty_tolerance_pct,
        rule_book_config=rule_book_config,
    )
    new_status = _compute_three_way_audit_status(so, match)
    previous = so.three_way_match_status
    so.three_way_match_status = new_status
    so.status = _derive_status(match, so)
    audit_invoice_id = invoice_id_for_audit or so.invoice_id or so.so_document_id
    if new_status != previous or audit_on_sync:
        await log_event(
            session,
            "three_way_match_evaluated",
            invoice_id=audit_invoice_id,
            tenant_id=so.tenant_id,
            detail=_three_way_match_audit_detail(so, match, new_status, inv=inv),
        )
    return new_status, match


def _derive_status(match: ThreeWayMatchResult, so: SalesOrder) -> SalesOrderStatus:
    if match.status == "3-Way Match":
        return SalesOrderStatus.MATCHED
    if match.status in ("Price Variance", "Qty Variance"):
        return SalesOrderStatus.VARIANCE_PENDING
    if match.status == "No DN":
        return SalesOrderStatus.OPEN
    return SalesOrderStatus.OPEN


def _sales_rule_from_ids(
    matched_rule_ids: list[str],
    config: RuleBookConfigPayload | None,
) -> tuple[str | None, str | None]:
    if config is None:
        return None, None
    for rid in matched_rule_ids:
        if not rid.startswith("sales:"):
            continue
        rule_id = rid.split(":", 1)[1]
        for rule in config.sales_rules:
            if rule.id == rule_id:
                return rule.name, rule.post_to.ledger
    return None, None


def _resolve_sales_match_mode(inv: Invoice | None) -> str:
    from app.services.classification.document_type_match_service import resolve_match_mode

    if inv is None:
        return "three_way_so_dn"
    return resolve_match_mode(document_type_code=inv.document_type_code)


def _attach_two_way_display(
    dn_qty: Decimal,
    dn_uom: str | None,
    inv: Invoice,
    match: ThreeWayMatchResult,
) -> ThreeWayMatchResult:
    inv_qty, inv_unit, _ = _invoice_qty_and_price(inv)
    inv_uom = getattr(inv.line_items[0], "uom", None) if inv.line_items else None
    dn_line = _amount_line(qty=dn_qty, uom=dn_uom, unit_price=None, line_value=match.po_value)
    invoice_line = _amount_line(
        qty=inv_qty,
        uom=inv_uom,
        unit_price=inv_unit,
        line_value=match.invoice_value,
    )
    display = ThreeWayMatchDisplay(
        po_on_document=dn_line,
        po_for_match=dn_line,
        grn_on_document=None,
        grn_for_match=None,
        invoice_on_document=invoice_line,
        invoice_for_match=invoice_line,
        match_explanation="DN qty ↔ Invoice qty",
    )
    return match.model_copy(update={"display": display})


def sales_order_to_response(
    so: SalesOrder,
    inv: Invoice | None,
    *,
    config: RuleBookConfigPayload | None = None,
) -> SalesOrderResponse:
    dn = _latest_dn(so)
    match_cfg = config.purchase_match if config is not None else None
    match_mode = _resolve_sales_match_mode(inv)

    if match_mode == "two_way_dn_invoice" and inv is not None:
        dn_qty = Decimal(str(dn.dn_qty)) if dn is not None else Decimal("0")
        dn_uom = getattr(dn, "dn_uom", None) if dn is not None else None
        match = compute_two_way_dn_match(
            dn_qty=dn_qty,
            dn_uom=dn_uom,
            inv=inv,
            match_config=match_cfg,
        )
        match = _attach_two_way_display(dn_qty, dn_uom, inv, match)
    else:
        match = compute_three_way_match(
            so,
            inv,
            match_config=match_cfg,
            rule_book_config=config,
        )
        match = _attach_match_display(so, inv, match)
    inv_qty, inv_unit, gst_rate = (Decimal("0"), Decimal("0"), 0.0)
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
            matched_rule_name, matched_gl = _sales_rule_from_ids(matched_rule_ids, config)
            if matched_gl is None and so.ledger:
                matched_gl = so.ledger
            if matched_gl is None:
                hit = resolve_config_mapping(inv, config)
                matched_gl = hit.mapping.expense_category
                if matched_rule_name is None and hit.rule_type == "Sales rule":
                    prefix = "Sales rule: "
                    if hit.match_reason.startswith(prefix):
                        matched_rule_name = hit.match_reason[len(prefix) :]
    elif so.ledger:
        matched_gl = so.ledger

    return SalesOrderResponse(
        id=so.id,
        so_number=so.so_number,
        customer=inv.vendor if inv is not None and inv.vendor else so.customer,
        so_date=so.so_date,
        item=so.item,
        requestor=so.requestor,
        so_qty=float(so.so_qty),
        so_unit_price=float(so.so_unit_price),
        dn_qty=float(dn.dn_qty) if dn else None,
        dn_date=dn.dn_date if dn else None,
        dn_shipper=dn.shipper if dn else None,
        dn_condition=dn.condition_note if dn else None,
        invoice_id=inv.id if inv is not None else so.invoice_id,
        so_document_id=so.so_document_id,
        dn_document_id=dn.dn_invoice_id if dn else None,
        invoice_no=inv.invoice_no if inv else None,
        invoice_qty=float(inv_qty),
        invoice_unit_price=float(inv_unit),
        gst_rate=gst_rate,
        variance_approved=so.variance_approved,
        status=so.status.value,
        three_way_match_status=so.three_way_match_status,
        match=match,
        match_mode=match_mode,
        route_target=route_target,
        evaluation_status=evaluation_status,
        matched_rule_ids=matched_rule_ids,
        matched_rule_name=matched_rule_name,
        matched_gl=matched_gl or so.ledger,
        ledger=so.ledger,
        sub_ledger=so.sub_ledger,
        sales_rule_id=so.sales_rule_id,
    )


async def list_sales_orders(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[SalesOrderResponse]:
    from app.services.sales.so_reference import is_plausible_so_reference

    rows = (
        await db.execute(
            select(SalesOrder)
            .where(SalesOrder.tenant_id == tenant_id)
            .options(selectinload(SalesOrder.delivery_notes))
            .order_by(SalesOrder.created_at.desc())
        )
    ).scalars().all()
    so_by_number = {so.so_number: so for so in rows}

    routed_invoices = (
        await db.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.route_target == ROUTE_SALES,
                Invoice.so_reference.isnot(None),
                Invoice.so_reference != "",
            )
            .options(selectinload(Invoice.line_items))
            .order_by(Invoice.created_at.desc())
        )
    ).scalars().all()

    config = await load_classification_config(db, tenant_id)
    responses: list[SalesOrderResponse] = []
    seen_pairs: set[tuple[int, int]] = set()
    sos_with_rows: set[int] = set()

    for inv in routed_invoices:
        if inv.sales_document_type in ("so", "dn"):
            continue
        so_number = (inv.so_reference or "").strip()
        if not is_plausible_so_reference(so_number):
            continue
        so = so_by_number.get(so_number)
        if so is None:
            continue
        key = (so.id, inv.id)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        sos_with_rows.add(so.id)
        responses.append(sales_order_to_response(so, inv, config=config))

    for so in rows:
        if so.id in sos_with_rows:
            continue
        inv = None
        if so.invoice_id:
            inv = (
                await db.execute(
                    select(Invoice)
                    .where(Invoice.id == so.invoice_id)
                    .options(selectinload(Invoice.line_items))
                )
            ).scalar_one_or_none()
        responses.append(sales_order_to_response(so, inv, config=config))

    return responses


async def list_two_way_sales_orphans(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[TwoWaySalesMatchResponse]:
    """DN ↔ invoice pairs on 2-way playbook without a sales-order register row."""
    from app.services.classification.document_type_match_service import resolve_match_mode

    routed = (
        await db.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.route_target == ROUTE_SALES,
                Invoice.sales_document_type.notin_(("so", "dn")),
            )
            .options(selectinload(Invoice.line_items))
            .order_by(Invoice.created_at.desc())
        )
    ).scalars().all()

    config = await load_classification_config(db, tenant_id)
    match_cfg = config.purchase_match if config is not None else None
    results: list[TwoWaySalesMatchResponse] = []
    seen_invoice_ids: set[int] = set()

    for inv in routed:
        if resolve_match_mode(document_type_code=inv.document_type_code) != "two_way_dn_invoice":
            continue
        if inv.id in seen_invoice_ids:
            continue
        so = await load_sales_order_for_invoice(db, inv)
        if so is not None:
            continue
        ctx = await resolve_ar_match_context(db, inv, requested_mode="two_way_dn_invoice")
        if ctx.effective_mode != "two_way_dn_invoice" or ctx.dn_invoice is None:
            continue
        seen_invoice_ids.add(inv.id)
        dn_qty, dn_uom = await _load_dn_invoice_qty(db, ctx.dn_invoice)
        match = compute_two_way_dn_match(
            dn_qty=dn_qty,
            dn_uom=dn_uom,
            inv=inv,
            match_config=match_cfg,
        )
        match = _attach_two_way_display(dn_qty, dn_uom, inv, match)
        inv_qty, inv_unit, gst_rate = _invoice_qty_and_price(inv)
        results.append(
            TwoWaySalesMatchResponse(
                invoice_id=inv.id,
                dn_invoice_id=ctx.dn_invoice.id,
                invoice_no=inv.invoice_no,
                customer=inv.vendor,
                dn_qty=float(dn_qty),
                invoice_qty=float(inv_qty),
                invoice_unit_price=float(inv_unit),
                gst_rate=gst_rate,
                match=match,
                route_target=inv.route_target,
                evaluation_status=inv.evaluation_status,
                document_type_code=inv.document_type_code,
            )
        )
    return results


def filter_two_way_sales_rows(rows: list[SalesOrderResponse]) -> list[SalesOrderResponse]:
    return [row for row in rows if row.match_mode == "two_way_dn_invoice"]


async def load_sales_order_for_invoice(
    db: AsyncSession,
    invoice: Invoice,
) -> SalesOrder | None:
    from app.services.sales.so_reference import is_plausible_so_reference

    so_number = (invoice.so_reference or "").strip()
    if not so_number or not is_plausible_so_reference(so_number):
        return None
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


async def record_delivery_note(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sales_order_id: int,
    body: DeliveryNoteCreate,
) -> SalesOrderResponse:
    so = (
        await db.execute(
            select(SalesOrder)
            .where(
                SalesOrder.id == sales_order_id,
                SalesOrder.tenant_id == tenant_id,
            )
            .options(selectinload(SalesOrder.delivery_notes))
        )
    ).scalar_one_or_none()
    if so is None:
        raise LookupError("Sales order not found")

    dn = DeliveryNote(
        tenant_id=so.tenant_id,
        sales_order_id=so.id,
        dn_qty=body.dn_qty,
        dn_date=body.dn_date or date.today(),
        shipper=body.shipper,
        condition_note=body.condition_note,
    )
    db.add(dn)
    await db.flush()
    await db.refresh(so, attribute_names=["delivery_notes"])

    inv: Invoice | None = None
    if so.invoice_id:
        inv = (
            await db.execute(
                select(Invoice)
                .where(Invoice.id == so.invoice_id)
                .options(selectinload(Invoice.line_items))
            )
        ).scalar_one_or_none()

    config = await load_classification_config(db, tenant_id)
    await persist_three_way_match_audit(
        db,
        so,
        inv,
        invoice_id_for_audit=so.invoice_id,
        rule_book_config=config,
    )
    return sales_order_to_response(so, inv, config=config)


async def approve_sales_variance(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sales_order_id: int,
) -> SalesOrderResponse:
    so = (
        await db.execute(
            select(SalesOrder)
            .where(
                SalesOrder.id == sales_order_id,
                SalesOrder.tenant_id == tenant_id,
            )
            .options(selectinload(SalesOrder.delivery_notes))
        )
    ).scalar_one_or_none()
    if so is None:
        raise LookupError("Sales order not found")

    so.variance_approved = True
    inv: Invoice | None = None
    if so.invoice_id:
        inv = (
            await db.execute(
                select(Invoice)
                .where(Invoice.id == so.invoice_id)
                .options(selectinload(Invoice.line_items))
            )
        ).scalar_one_or_none()

    config = await load_classification_config(db, tenant_id)
    await persist_three_way_match_audit(
        db,
        so,
        inv,
        invoice_id_for_audit=so.invoice_id,
        rule_book_config=config,
    )
    return sales_order_to_response(so, inv, config=config)


@dataclass(frozen=True)
class ARMatchContext:
    effective_mode: str
    so: SalesOrder | None
    dn: DeliveryNote | None
    dn_invoice: Invoice | None


def compute_two_way_dn_match(
    *,
    dn_qty: Decimal,
    dn_uom: str | None,
    inv: Invoice,
    match_config: PurchaseMatchConfig | None = None,
    qty_tolerance_pct: float | None = None,
) -> ThreeWayMatchResult:
    """Qty-only DN ↔ invoice match when no sales order baseline exists."""
    cfg = match_config or PurchaseMatchConfig()
    tolerance = cfg.qty_tolerance_pct if qty_tolerance_pct is None else qty_tolerance_pct
    inv_qty, inv_unit, gst_rate = _invoice_qty_and_price(inv)
    invoice_value = _round2(inv_qty * inv_unit)
    invoice_gst = _round2(Decimal(str(invoice_value)) * Decimal(str(gst_rate)))
    invoice_total = _round2(Decimal(str(invoice_value)) + Decimal(str(invoice_gst)))

    dn_value = _round2(float(dn_qty) * float(inv_unit))
    qty_variance = _round2((float(inv_qty) - float(dn_qty)) * float(inv_unit))

    if _qty_over_billing(inv_qty, dn_qty, tolerance_pct=tolerance):
        status = "Qty Variance"
    else:
        status = "2-Way Match"

    return ThreeWayMatchResult(
        status=status,
        qty_variance_value=qty_variance,
        price_variance_value=0.0,
        total_deviation=qty_variance,
        po_value=dn_value,
        invoice_value=invoice_value,
        invoice_gst=invoice_gst,
        invoice_total=invoice_total,
    )


def compute_two_way_so_match(
    so: SalesOrder,
    inv: Invoice,
    *,
    match_config: PurchaseMatchConfig | None = None,
) -> ThreeWayMatchResult:
    """SO ↔ invoice match when no delivery note exists on the dossier."""
    from app.services.classification.document_type_match_service import (
        PRICE_MATCH_CAP_AUD,
        PRICE_MATCH_PCT,
        _price_variance_exceeds_tolerance,
    )

    inv_qty, inv_unit, gst_rate = _invoice_qty_and_price(inv)
    so_qty = Decimal(str(so.so_qty or 0))
    so_unit = Decimal(str(so.so_unit_price or 0))
    so_value = _round2(so_qty * so_unit)
    invoice_value = _round2(inv_qty * inv_unit)
    invoice_gst = _round2(Decimal(str(invoice_value)) * Decimal(str(gst_rate)))
    invoice_total = _round2(Decimal(str(invoice_value)) + Decimal(str(invoice_gst)))

    if so.variance_approved:
        return ThreeWayMatchResult(
            status="2-Way Match",
            qty_variance_value=0.0,
            price_variance_value=0.0,
            total_deviation=0.0,
            po_value=so_value,
            invoice_value=invoice_value,
            invoice_gst=invoice_gst,
            invoice_total=invoice_total,
        )

    inv_qty_f = float(inv_qty)
    inv_unit_f = float(inv_unit)
    so_qty_f = float(so_qty)
    so_unit_f = float(so_unit)
    price_variance = _round2((inv_unit_f - so_unit_f) * inv_qty_f)

    if _price_variance_exceeds_tolerance(
        price_variance=price_variance,
        po_unit=so_unit_f,
        po_qty=so_qty_f,
    ):
        return ThreeWayMatchResult(
            status="Price Variance",
            qty_variance_value=0.0,
            price_variance_value=price_variance,
            total_deviation=price_variance,
            po_value=so_value,
            invoice_value=invoice_value,
            invoice_gst=invoice_gst,
            invoice_total=invoice_total,
        )

    if inv_qty_f > so_qty_f:
        return ThreeWayMatchResult(
            status="Qty Variance",
            qty_variance_value=_round2((inv_qty_f - so_qty_f) * inv_unit_f),
            price_variance_value=0.0,
            total_deviation=_round2((inv_qty_f - so_qty_f) * inv_unit_f),
            po_value=so_value,
            invoice_value=invoice_value,
            invoice_gst=invoice_gst,
            invoice_total=invoice_total,
        )

    inv_total = float(inv.subtotal or inv.total or Decimal("0"))
    if inv_total > 0 and so_value > 0 and inv_total > so_value * 1.02 + float(PRICE_MATCH_CAP_AUD):
        return ThreeWayMatchResult(
            status="Qty Variance",
            qty_variance_value=_round2(inv_total - so_value),
            price_variance_value=0.0,
            total_deviation=_round2(inv_total - so_value),
            po_value=so_value,
            invoice_value=invoice_value,
            invoice_gst=invoice_gst,
            invoice_total=invoice_total,
        )

    return ThreeWayMatchResult(
        status="2-Way Match",
        qty_variance_value=0.0,
        price_variance_value=price_variance,
        total_deviation=price_variance,
        po_value=so_value,
        invoice_value=invoice_value,
        invoice_gst=invoice_gst,
        invoice_total=invoice_total,
    )


async def _load_dn_invoice_qty(
    session: AsyncSession,
    dn_invoice: Invoice,
) -> tuple[Decimal, str | None]:
    loaded = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == dn_invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one_or_none()
    row = loaded or dn_invoice
    qty, _, _ = _invoice_qty_and_price(row)
    dn_uom = getattr(row.line_items[0], "uom", None) if row.line_items else None
    return qty, dn_uom


async def resolve_ar_match_context(
    session: AsyncSession,
    invoice: Invoice,
    *,
    requested_mode: str = "three_way_so_dn",
) -> ARMatchContext:
    """Pick 3-way SO path, 2-way DN path, or no automated match."""
    from app.models.invoice import SalesDocumentType
    from app.services.sales.sales_linking_service import find_dn_invoices_by_invoice_no

    mode = (requested_mode or "three_way_so_dn").strip().lower()
    adaptive_modes = {"three_way_so_dn", "two_way_so_invoice", "two_way_dn_invoice"}
    if mode not in adaptive_modes:
        return ARMatchContext(effective_mode="none", so=None, dn=None, dn_invoice=None)

    so = await load_sales_order_for_invoice(session, invoice)
    if so is not None:
        dn = _latest_dn(so)
        if dn is not None:
            return ARMatchContext(
                effective_mode="three_way_so_dn",
                so=so,
                dn=dn,
                dn_invoice=None,
            )
        return ARMatchContext(
            effective_mode="two_way_so_invoice",
            so=so,
            dn=None,
            dn_invoice=None,
        )

    invoice_no = (invoice.invoice_no or "").strip()
    dn_candidates: list[Invoice] = []
    if invoice_no:
        dn_candidates = await find_dn_invoices_by_invoice_no(
            session,
            tenant_id=invoice.tenant_id,
            invoice_no=invoice_no,
            include_linked=True,
        )

    if invoice_no and not dn_candidates:
        rows = (
            await session.execute(
                select(Invoice)
                .where(
                    Invoice.tenant_id == invoice.tenant_id,
                    Invoice.sales_document_type == SalesDocumentType.DN.value,
                    Invoice.status.notin_(
                        {
                            InvoiceStatus.DUPLICATE_SKIPPED,
                            InvoiceStatus.REJECTED,
                        }
                    ),
                )
                .order_by(Invoice.id.desc())
                .limit(20)
            )
        ).scalars().all()
        token = invoice_no.upper() if invoice_no else ""
        for row in rows:
            row_no = (row.invoice_no or "").strip().upper()
            if token and row_no == token:
                dn_candidates.append(row)

    if dn_candidates:
        return ARMatchContext(
            effective_mode="two_way_dn_invoice",
            so=None,
            dn=None,
            dn_invoice=dn_candidates[0],
        )

    return ARMatchContext(effective_mode="none", so=None, dn=None, dn_invoice=None)


def _sales_match_result_to_outcome(
    match: ThreeWayMatchResult,
    *,
    match_mode: str,
) -> object:
    from app.services.classification.document_type_match_service import DocumentMatchOutcome

    if match.status == "No DN":
        return DocumentMatchOutcome(
            passed=False,
            status="No DN",
            message="Delivery note required before invoice can match sales order",
            match_mode=match_mode,
            detail={},
        )
    if match.status == "Qty Variance":
        return DocumentMatchOutcome(
            passed=False,
            status="Qty Variance",
            message="Qty over-billing — invoice qty exceeds DN (0% tolerance)",
            match_mode=match_mode,
            detail={"qty_variance_value": match.qty_variance_value},
        )
    if match.status == "Price Variance":
        return DocumentMatchOutcome(
            passed=False,
            status="Price Variance",
            message=f"Price variance {match.price_variance_value} exceeds tolerance",
            match_mode=match_mode,
            detail={"price_variance_value": match.price_variance_value},
        )
    label = (
        "2-Way Match"
        if match_mode in {"two_way_dn_invoice", "two_way_so_invoice"}
        else match.status
    )
    return DocumentMatchOutcome(
        passed=True,
        status=label,
        message=label,
        match_mode=match_mode,
        detail={
            "qty_variance_value": match.qty_variance_value,
            "price_variance_value": match.price_variance_value,
        },
    )


async def execute_ar_document_match(
    match_mode: str,
    *,
    session: AsyncSession,
    invoice: Invoice,
) -> object:
    """Run tiered AR match (3-way SO or 2-way DN) for the invoice pipeline."""
    requested = (match_mode or "three_way_so_dn").strip().lower()
    ctx = await resolve_ar_match_context(session, invoice, requested_mode=requested)

    if ctx.effective_mode == "none":
        from app.services.classification.document_type_match_service import DocumentMatchOutcome

        return DocumentMatchOutcome(
            passed=True,
            status="Skipped",
            message="No SO or DN fulfilment evidence — match skipped",
            match_mode="none",
            detail={},
        )

    if ctx.effective_mode == "three_way_so_dn" and ctx.so is not None:
        match = compute_three_way_match(ctx.so, invoice)
        return _sales_match_result_to_outcome(match, match_mode="three_way_so_dn")

    if ctx.effective_mode == "two_way_so_invoice" and ctx.so is not None:
        match = compute_two_way_so_match(ctx.so, invoice)
        return _sales_match_result_to_outcome(match, match_mode="two_way_so_invoice")

    if ctx.effective_mode == "two_way_dn_invoice" and ctx.dn_invoice is not None:
        dn_qty, dn_uom = await _load_dn_invoice_qty(session, ctx.dn_invoice)
        match = compute_two_way_dn_match(dn_qty=dn_qty, dn_uom=dn_uom, inv=invoice)
        return _sales_match_result_to_outcome(match, match_mode="two_way_dn_invoice")

    from app.services.classification.document_type_match_service import DocumentMatchOutcome

    await log_event(
        session,
        "match_context_incomplete",
        invoice_id=invoice.id,
        detail={
            "requested_mode": requested,
            "effective_mode": ctx.effective_mode,
            "message": "AR match context incomplete",
        },
    )
    return DocumentMatchOutcome(
        passed=False,
        status="Match context incomplete",
        message="AR match context incomplete — link SO/DN or upload supporting documents",
        match_mode=requested,
        detail={"effective_mode": ctx.effective_mode},
    )
