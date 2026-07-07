"""Three-way match for purchase orders, goods receipts, and invoices."""

from __future__ import annotations

from dataclasses import dataclass
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
from app.services.invoice.invoice_evaluation_service import ROUTE_PURCHASE, parse_matched_rule_ids
from app.services.purchase.purchase_coding_service import (
    code_po_from_invoice,
    inherit_po_coding_to_invoice,
)
from app.services.audit.audit_detail_helpers import (
    compute_three_way_audit_status,
    three_way_match_audit_detail,
)
from app.services.audit.audit_service import log_event
from app.services.rule_book.rule_book_mapper import load_classification_config, resolve_config_mapping

ROUTE_PURCHASE_MANAGEMENT = ROUTE_PURCHASE


def _round2(value: Decimal | float) -> float:
    return round(float(value), 2)


def _qty_over_billing(
    invoice_qty: Decimal,
    grn_qty: Decimal,
    *,
    tolerance_pct: float = 0.0,
) -> bool:
    """True when invoice exceeds GRN qty beyond configured tolerance."""
    if grn_qty <= 0:
        return invoice_qty > 0
    allowed = grn_qty * (Decimal("1") + Decimal(str(tolerance_pct)) / Decimal("100"))
    return invoice_qty > allowed


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


def build_three_way_match_display(
    po: PurchaseOrder,
    inv: Invoice | None,
    match: ThreeWayMatchResult,
) -> ThreeWayMatchDisplay:
    grn = _latest_grn(po)

    po_qty = Decimal(str(po.po_qty or 0))
    po_unit = Decimal(str(po.po_unit_price or 0))
    po_line = _amount_line(
        qty=po_qty,
        uom=getattr(po, "po_uom", None),
        unit_price=po_unit,
        line_value=match.po_value,
    )

    invoice_line: MatchAmountLine | None = None
    if inv is not None:
        inv_qty, inv_unit, _ = _invoice_qty_and_price(inv)
        inv_uom = None
        if inv.line_items:
            inv_uom = getattr(inv.line_items[0], "uom", None)
        invoice_line = _amount_line(
            qty=inv_qty,
            uom=inv_uom,
            unit_price=inv_unit,
            line_value=match.invoice_value,
        )

    grn_line: MatchAmountLine | None = None
    if grn is not None:
        grn_qty = Decimal(str(grn.grn_qty or 0))
        grn_line = _amount_line(
            qty=grn_qty,
            uom=getattr(grn, "grn_uom", None),
            unit_price=None,
            line_value=None,
        )

    return ThreeWayMatchDisplay(
        po_on_document=po_line,
        po_for_match=po_line,
        grn_on_document=grn_line,
        grn_for_match=grn_line,
        invoice_on_document=invoice_line,
        invoice_for_match=invoice_line,
    )


def _attach_match_display(
    po: PurchaseOrder,
    inv: Invoice | None,
    match: ThreeWayMatchResult,
) -> ThreeWayMatchResult:
    display = build_three_way_match_display(po, inv, match)
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
    from app.services.extraction.gst_rate import invoice_gst_rate_fraction

    gst_rate = invoice_gst_rate_fraction(inv)
    if gst_rate is None:
        gst_rate = 0.0
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
    rule_book_config: RuleBookConfigPayload | None = None,
) -> ThreeWayMatchResult:
    cfg = match_config or PurchaseMatchConfig()
    tolerance = cfg.qty_tolerance_pct if qty_tolerance_pct is None else qty_tolerance_pct
    grn = _latest_grn(po)

    po_qty = Decimal(str(po.po_qty or 0))
    po_unit = Decimal(str(po.po_unit_price or 0))
    po_value = _round2(po_qty * po_unit)

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

    grn_qty = Decimal(str(grn.grn_qty or 0))
    qty_variance = _round2((float(inv_qty) - float(grn_qty)) * float(inv_unit))
    price_variance = _round2((float(inv_unit) - float(po_unit)) * float(inv_qty))
    total_deviation = _round2(qty_variance + price_variance)

    if po.variance_approved:
        status = "3-Way Match"
    elif price_variance != 0:
        status = "Price Variance"
    elif _qty_over_billing(inv_qty, grn_qty, tolerance_pct=tolerance):
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

    match = compute_three_way_match(
        po,
        inv,
        match_config=cfg,
        qty_tolerance_pct=qty_tolerance_pct,
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


def _resolve_purchase_match_mode(inv: Invoice | None) -> str:
    from app.services.classification.document_type_match_service import resolve_match_mode

    if inv is None:
        return "three_way_po_grn"
    return resolve_match_mode(document_type_code=inv.document_type_code)


def _two_way_outcome_to_match_result(
    po: PurchaseOrder,
    inv: Invoice,
    *,
    status: str,
    price_variance: float = 0.0,
    qty_variance: float = 0.0,
) -> ThreeWayMatchResult:
    inv_qty, inv_unit, gst_rate = _invoice_qty_and_price(inv)
    po_qty = Decimal(str(po.po_qty or 0))
    po_unit = Decimal(str(po.po_unit_price or 0))
    po_value = _round2(po_qty * po_unit)
    invoice_value = _round2(inv_qty * inv_unit)
    invoice_gst = _round2(Decimal(str(invoice_value)) * Decimal(str(gst_rate)))
    invoice_total = _round2(Decimal(str(invoice_value)) + Decimal(str(invoice_gst)))
    total_deviation = _round2(qty_variance + price_variance)
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


def _attach_purchase_two_way_display(
    po: PurchaseOrder,
    inv: Invoice,
    match: ThreeWayMatchResult,
) -> ThreeWayMatchResult:
    po_qty = Decimal(str(po.po_qty or 0))
    po_unit = Decimal(str(po.po_unit_price or 0))
    inv_qty, inv_unit, _ = _invoice_qty_and_price(inv)
    inv_uom = getattr(inv.line_items[0], "uom", None) if inv.line_items else None
    po_line = _amount_line(
        qty=po_qty,
        uom=getattr(po, "po_uom", None),
        unit_price=po_unit,
        line_value=match.po_value,
    )
    invoice_line = _amount_line(
        qty=inv_qty,
        uom=inv_uom,
        unit_price=inv_unit,
        line_value=match.invoice_value,
    )
    display = ThreeWayMatchDisplay(
        po_on_document=po_line,
        po_for_match=po_line,
        grn_on_document=None,
        grn_for_match=None,
        invoice_on_document=invoice_line,
        invoice_for_match=invoice_line,
        match_explanation="PO qty/price ↔ Invoice qty/price",
    )
    return match.model_copy(update={"display": display})


def purchase_order_to_response(
    po: PurchaseOrder,
    inv: Invoice | None,
    *,
    config: RuleBookConfigPayload | None = None,
) -> PurchaseOrderResponse:
    grn = _latest_grn(po)
    match_cfg = config.purchase_match if config is not None else None
    match_mode = _resolve_purchase_match_mode(inv)
    effective_mode = match_mode
    if inv is not None and match_mode == "three_way_po_grn":
        effective_mode = "three_way_po_grn" if grn is not None else "two_way_po_ses"

    if effective_mode == "two_way_po_ses" and inv is not None:
        from app.services.classification.document_type_match_service import compute_two_way_po_match

        outcome = compute_two_way_po_match(po, inv)
        detail = outcome.detail or {}
        match = _two_way_outcome_to_match_result(
            po,
            inv,
            status=outcome.status,
            price_variance=float(detail.get("price_variance_value") or 0.0),
            qty_variance=0.0,
        )
        match = _attach_purchase_two_way_display(po, inv, match)
    else:
        match = compute_three_way_match(
            po,
            inv,
            match_config=match_cfg,
            rule_book_config=config,
        )
        match = _attach_match_display(po, inv, match)
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
        match_mode=match_mode,
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
    from app.services.purchase.po_reference import is_plausible_po_reference

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


def filter_two_way_purchase_rows(rows: list[PurchaseOrderResponse]) -> list[PurchaseOrderResponse]:
    return [
        row
        for row in rows
        if row.match_mode in {"two_way_po_ses", "two_way_grn_invoice"}
    ]


@dataclass(frozen=True)
class APMatchContext:
    effective_mode: str
    po: PurchaseOrder | None
    grn: GoodsReceipt | None
    grn_invoice: Invoice | None


def compute_two_way_grn_match(
    *,
    grn_qty: Decimal,
    inv: Invoice,
    match_config: PurchaseMatchConfig | None = None,
    qty_tolerance_pct: float | None = None,
) -> ThreeWayMatchResult:
    """Qty-only GRN ↔ invoice match when no purchase order baseline exists."""
    cfg = match_config or PurchaseMatchConfig()
    tolerance = cfg.qty_tolerance_pct if qty_tolerance_pct is None else qty_tolerance_pct
    inv_qty, inv_unit, gst_rate = _invoice_qty_and_price(inv)
    invoice_value = _round2(inv_qty * inv_unit)
    invoice_gst = _round2(Decimal(str(invoice_value)) * Decimal(str(gst_rate)))
    invoice_total = _round2(Decimal(str(invoice_value)) + Decimal(str(invoice_gst)))

    grn_value = _round2(float(grn_qty) * float(inv_unit))
    qty_variance = _round2((float(inv_qty) - float(grn_qty)) * float(inv_unit))

    if _qty_over_billing(inv_qty, grn_qty, tolerance_pct=tolerance):
        status = "Qty Variance"
    else:
        status = "2-Way Match"

    return ThreeWayMatchResult(
        status=status,
        qty_variance_value=qty_variance,
        price_variance_value=0.0,
        total_deviation=qty_variance,
        po_value=grn_value,
        invoice_value=invoice_value,
        invoice_gst=invoice_gst,
        invoice_total=invoice_total,
    )


async def _load_grn_invoice_qty(
    session: AsyncSession,
    grn_invoice: Invoice,
) -> Decimal:
    loaded = (
        await session.execute(
            select(Invoice)
            .where(Invoice.id == grn_invoice.id)
            .options(selectinload(Invoice.line_items))
        )
    ).scalar_one_or_none()
    row = loaded or grn_invoice
    qty, _, _ = _invoice_qty_and_price(row)
    return qty


async def resolve_purchase_match_context(
    session: AsyncSession,
    invoice: Invoice,
    *,
    requested_mode: str = "three_way_po_grn",
) -> APMatchContext:
    """Pick 3-way PO path, 2-way PO or GRN path, or no automated match."""
    from app.services.purchase.purchase_linking_service import find_grn_invoices_by_invoice_no

    mode = (requested_mode or "three_way_po_grn").strip().lower()
    adaptive_modes = {"three_way_po_grn", "two_way_po_ses", "two_way_grn_invoice"}
    if mode not in adaptive_modes:
        return APMatchContext(effective_mode="none", po=None, grn=None, grn_invoice=None)

    po = await load_purchase_order_for_invoice(session, invoice)
    if po is not None:
        grn = _latest_grn(po)
        if grn is not None:
            return APMatchContext(
                effective_mode="three_way_po_grn",
                po=po,
                grn=grn,
                grn_invoice=None,
            )
        return APMatchContext(
            effective_mode="two_way_po_ses",
            po=po,
            grn=None,
            grn_invoice=None,
        )

    invoice_no = (invoice.invoice_no or "").strip()
    grn_candidates: list[Invoice] = []
    if invoice_no:
        grn_candidates = await find_grn_invoices_by_invoice_no(
            session,
            tenant_id=invoice.tenant_id,
            invoice_no=invoice_no,
            include_linked=True,
        )

    if grn_candidates:
        return APMatchContext(
            effective_mode="two_way_grn_invoice",
            po=None,
            grn=None,
            grn_invoice=grn_candidates[0],
        )

    return APMatchContext(effective_mode="none", po=None, grn=None, grn_invoice=None)


def _purchase_match_result_to_outcome(
    match: ThreeWayMatchResult,
    *,
    match_mode: str,
) -> object:
    from app.services.classification.document_type_match_service import DocumentMatchOutcome

    if match.status == "No GRN":
        return DocumentMatchOutcome(
            passed=False,
            status="No GRN",
            message="GRN required before invoice can match PO",
            match_mode=match_mode,
            detail={},
        )
    if match.status == "Qty Variance":
        return DocumentMatchOutcome(
            passed=False,
            status="Qty Variance",
            message="Qty over-billing — invoice qty exceeds received quantity (0% tolerance)",
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
        if match_mode in {"two_way_po_ses", "two_way_grn_invoice"}
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


async def execute_purchase_document_match(
    match_mode: str,
    *,
    session: AsyncSession,
    invoice: Invoice,
) -> object:
    """Run tiered AP match (3-way PO, 2-way PO, or 2-way GRN) for the invoice pipeline."""
    from app.services.classification.document_type_match_service import compute_two_way_po_match

    requested = (match_mode or "three_way_po_grn").strip().lower()
    ctx = await resolve_purchase_match_context(session, invoice, requested_mode=requested)

    if ctx.effective_mode == "none":
        from app.services.classification.document_type_match_service import DocumentMatchOutcome

        return DocumentMatchOutcome(
            passed=True,
            status="Skipped",
            message="No PO or GRN fulfilment evidence — match skipped",
            match_mode="none",
            detail={},
        )

    if ctx.effective_mode == "three_way_po_grn" and ctx.po is not None:
        match = compute_three_way_match(ctx.po, invoice)
        if match.status == "No GRN":
            return _purchase_match_result_to_outcome(match, match_mode="three_way_po_grn")
        po_unit = float(ctx.po.po_unit_price)
        from app.services.classification.document_type_match_service import _price_variance_exceeds_tolerance

        if po_unit > 0 and _price_variance_exceeds_tolerance(
            price_variance=match.price_variance_value,
            po_unit=po_unit,
            po_qty=float(ctx.po.po_qty),
        ):
            return _purchase_match_result_to_outcome(match, match_mode="three_way_po_grn")
        return _purchase_match_result_to_outcome(match, match_mode="three_way_po_grn")

    if ctx.effective_mode == "two_way_po_ses" and ctx.po is not None:
        outcome = compute_two_way_po_match(ctx.po, invoice)
        return outcome

    if ctx.effective_mode == "two_way_grn_invoice" and ctx.grn_invoice is not None:
        grn_qty = await _load_grn_invoice_qty(session, ctx.grn_invoice)
        match = compute_two_way_grn_match(grn_qty=grn_qty, inv=invoice)
        return _purchase_match_result_to_outcome(match, match_mode="two_way_grn_invoice")

    from app.services.classification.document_type_match_service import DocumentMatchOutcome

    await log_event(
        session,
        "match_context_incomplete",
        invoice_id=invoice.id,
        detail={
            "requested_mode": requested,
            "effective_mode": ctx.effective_mode,
            "message": "AP match context incomplete",
        },
    )
    return DocumentMatchOutcome(
        passed=False,
        status="Match context incomplete",
        message="AP match context incomplete — link PO/GRN or upload supporting documents",
        match_mode=requested,
        detail={"effective_mode": ctx.effective_mode},
    )


async def sync_purchase_order_from_invoice(
    db: AsyncSession,
    invoice: Invoice,
) -> PurchaseOrder | None:
    """Backward-compatible alias for PO-first purchase document sync."""
    from app.services.purchase.purchase_document_service import sync_purchase_document

    return await sync_purchase_document(db, invoice)


async def load_purchase_order_for_invoice(
    db: AsyncSession,
    invoice: Invoice,
) -> PurchaseOrder | None:
    from app.services.purchase.po_reference import is_plausible_po_reference

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
