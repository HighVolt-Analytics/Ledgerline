"""Shared line-level matching for purchase and sales three-way / two-way match."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any, Literal

FUZZY_DESC_THRESHOLD = 0.86

LineStatus = Literal[
    "match",
    "price_variance",
    "qty_variance",
    "uom_mismatch",
    "unmatched_invoice",
    "order_only",
    "missing_qty",
]


@dataclass
class MatchLineInput:
    """Normalized line for pairing (order, receipt, or invoice)."""

    key: str | int | None = None
    description: str | None = None
    sku: str | None = None
    qty: Decimal | None = None
    uom: str | None = None
    unit_price: Decimal | None = None
    line_value: Decimal | None = None


@dataclass
class LineMatchResult:
    status: LineStatus
    description: str | None = None
    sku: str | None = None
    order_qty: float | None = None
    order_uom: str | None = None
    order_unit_price: float | None = None
    received_qty: float | None = None
    received_uom: str | None = None
    invoice_qty: float | None = None
    invoice_uom: str | None = None
    invoice_unit_price: float | None = None
    qty_variance_value: float = 0.0
    price_variance_value: float = 0.0
    order_line_key: str | int | None = None
    invoice_line_key: str | int | None = None


@dataclass
class LineMatchRollup:
    status: str
    qty_variance_value: float = 0.0
    price_variance_value: float = 0.0
    total_deviation: float = 0.0
    order_value: float = 0.0
    invoice_value: float = 0.0
    line_results: list[LineMatchResult] = field(default_factory=list)
    order_qty_total: float = 0.0
    received_qty_total: float = 0.0
    invoice_qty_total: float = 0.0
    order_unit_price_weighted: float | None = None
    invoice_unit_price_weighted: float | None = None
    order_uom: str | None = None
    received_uom: str | None = None
    invoice_uom: str | None = None


def _round2(value: Decimal | float) -> float:
    return round(float(value), 2)


def _norm_sku(sku: str | None) -> str | None:
    if sku is None:
        return None
    cleaned = " ".join(str(sku).strip().upper().split())
    return cleaned or None


def _norm_desc(desc: str | None) -> str | None:
    if desc is None:
        return None
    cleaned = " ".join(str(desc).strip().lower().split())
    return cleaned or None


def _norm_uom(uom: str | None) -> str | None:
    if uom is None:
        return None
    cleaned = str(uom).strip().upper()
    return cleaned or None


def _as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def resolve_unit_price(
    *,
    unit_price: Decimal | float | None,
    line_value: Decimal | float | None = None,
    amount: Decimal | float | None = None,
    qty: Decimal | float | None = None,
) -> Decimal | None:
    up = _as_decimal(unit_price)
    if up is not None:
        return up
    value = _as_decimal(line_value)
    if value is None:
        value = _as_decimal(amount)
    q = _as_decimal(qty)
    if value is not None and q is not None and q != 0:
        return value / q
    return None


def resolve_line_value(
    *,
    line_value: Decimal | float | None = None,
    amount: Decimal | float | None = None,
    unit_price: Decimal | float | None = None,
    qty: Decimal | float | None = None,
) -> Decimal | None:
    value = _as_decimal(line_value)
    if value is not None:
        return value
    value = _as_decimal(amount)
    if value is not None:
        return value
    up = _as_decimal(unit_price)
    q = _as_decimal(qty)
    if up is not None and q is not None:
        return up * q
    return None


def line_input_from_invoice_item(item: Any, *, key: str | int | None = None) -> MatchLineInput:
    qty = _as_decimal(getattr(item, "qty", None))
    unit = resolve_unit_price(
        unit_price=getattr(item, "unit_price", None),
        amount=getattr(item, "amount", None),
        qty=qty,
    )
    value = resolve_line_value(
        amount=getattr(item, "amount", None),
        unit_price=unit,
        qty=qty,
    )
    return MatchLineInput(
        key=key if key is not None else getattr(item, "id", None),
        description=getattr(item, "description", None),
        sku=getattr(item, "sku", None),
        qty=qty,
        uom=getattr(item, "uom", None),
        unit_price=unit,
        line_value=value,
    )


def line_input_from_order_line(item: Any, *, key: str | int | None = None) -> MatchLineInput:
    qty = _as_decimal(getattr(item, "qty", None))
    unit = resolve_unit_price(
        unit_price=getattr(item, "unit_price", None),
        line_value=getattr(item, "line_value", None),
        qty=qty,
    )
    value = resolve_line_value(
        line_value=getattr(item, "line_value", None),
        unit_price=unit,
        qty=qty,
    )
    resolved_key = key
    if resolved_key is None:
        resolved_key = getattr(item, "id", None)
    if resolved_key is None:
        line_no = getattr(item, "line_no", None)
        if line_no is not None:
            resolved_key = f"line-{line_no}"
    return MatchLineInput(
        key=resolved_key,
        description=getattr(item, "description", None),
        sku=getattr(item, "sku", None),
        qty=qty,
        uom=getattr(item, "uom", None),
        unit_price=unit,
        line_value=value,
    )


def _desc_similarity(a: str | None, b: str | None) -> float:
    na, nb = _norm_desc(a), _norm_desc(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def pair_order_to_invoice(
    order_lines: list[MatchLineInput],
    invoice_lines: list[MatchLineInput],
) -> tuple[list[tuple[MatchLineInput, MatchLineInput]], list[MatchLineInput], list[MatchLineInput]]:
    """Greedy 1:1 pairing: SKU exact, then exact/fuzzy description.

    Single-line × single-line always pairs (header-only PO/SO vs one invoice line).
    """
    if len(order_lines) == 1 and len(invoice_lines) == 1:
        return [(order_lines[0], invoice_lines[0])], [], []

    remaining_inv = list(enumerate(invoice_lines))
    paired: list[tuple[MatchLineInput, MatchLineInput]] = []
    used_inv: set[int] = set()

    def _take_inv(pred) -> MatchLineInput | None:
        best_i: int | None = None
        best_score = -1.0
        for idx, inv in remaining_inv:
            if idx in used_inv:
                continue
            score = pred(inv)
            if score is None:
                continue
            if score > best_score:
                best_score = score
                best_i = idx
        if best_i is None:
            return None
        used_inv.add(best_i)
        return invoice_lines[best_i]

    # Pass 1: exact SKU
    for order in order_lines:
        osku = _norm_sku(order.sku)
        if not osku:
            continue
        inv = _take_inv(lambda i, sku=osku: 1.0 if _norm_sku(i.sku) == sku else None)
        if inv is not None:
            paired.append((order, inv))

    unpaired_orders = [o for o in order_lines if all(o is not p[0] for p in paired)]

    # Pass 2: exact normalized description
    still: list[MatchLineInput] = []
    for order in unpaired_orders:
        odesc = _norm_desc(order.description)
        if not odesc:
            still.append(order)
            continue
        inv = _take_inv(lambda i, d=odesc: 1.0 if _norm_desc(i.description) == d else None)
        if inv is not None:
            paired.append((order, inv))
        else:
            still.append(order)

    # Pass 3: fuzzy description
    leftover_orders: list[MatchLineInput] = []
    for order in still:
        inv = _take_inv(
            lambda i, o=order: (
                sim
                if (sim := _desc_similarity(o.description, i.description)) >= FUZZY_DESC_THRESHOLD
                else None
            )
        )
        if inv is not None:
            paired.append((order, inv))
        else:
            leftover_orders.append(order)

    leftover_inv = [inv for i, inv in enumerate(invoice_lines) if i not in used_inv]
    return paired, leftover_orders, leftover_inv


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


def compute_line_match(
    *,
    order_lines: list[MatchLineInput],
    invoice_lines: list[MatchLineInput],
    received_qty_by_order_key: dict[str | int, Decimal] | None = None,
    received_uom_by_order_key: dict[str | int, str | None] | None = None,
    require_receipt: bool = True,
    receipt_present: bool = True,
    variance_approved: bool = False,
    qty_tolerance_pct: float = 0.0,
    missing_receipt_status: str = "No GRN",
    gst_rate: float = 0.0,
) -> LineMatchRollup:
    """Line-level match with finance-correct rollup rules."""
    received_qty_by_order_key = received_qty_by_order_key or {}
    received_uom_by_order_key = received_uom_by_order_key or {}

    # Fallback: header-only order with no lines — synthesize nothing; treat empty as no order lines.
    effective_order = list(order_lines)
    effective_invoice = list(invoice_lines)

    # Legacy / empty invoice lines: cannot invent qty=1.
    paired, leftover_orders, leftover_inv = pair_order_to_invoice(effective_order, effective_invoice)

    results: list[LineMatchResult] = []
    qty_var_total = Decimal("0")
    price_var_total = Decimal("0")
    order_value = Decimal("0")
    invoice_value = Decimal("0")
    order_qty_total = Decimal("0")
    received_qty_total = Decimal("0")
    invoice_qty_total = Decimal("0")
    any_price = False
    any_qty = False
    any_missing_qty = False
    any_uom = False
    any_unmatched_inv = False

    first_order_uom: str | None = None
    first_recv_uom: str | None = None
    first_inv_uom: str | None = None

    for order, inv in paired:
        o_qty = order.qty
        i_qty = inv.qty
        o_unit = order.unit_price or Decimal("0")
        i_unit = inv.unit_price
        if i_unit is None:
            i_unit = resolve_unit_price(unit_price=None, line_value=inv.line_value, qty=i_qty)
        i_unit = i_unit or Decimal("0")

        o_val = resolve_line_value(line_value=order.line_value, unit_price=o_unit, qty=o_qty) or Decimal("0")
        i_val = resolve_line_value(line_value=inv.line_value, unit_price=i_unit, qty=i_qty) or Decimal("0")
        order_value += o_val
        invoice_value += i_val

        o_key = order.key
        recv_qty = Decimal("0")
        if o_key is not None and o_key in received_qty_by_order_key:
            recv_qty = received_qty_by_order_key[o_key] or Decimal("0")
        elif require_receipt and receipt_present and len(effective_order) == 1 and received_qty_by_order_key:
            # Single order line: if receipts keyed differently, sum all received.
            recv_qty = sum(received_qty_by_order_key.values(), Decimal("0"))

        recv_uom = None
        if o_key is not None:
            recv_uom = received_uom_by_order_key.get(o_key)

        if o_qty is not None:
            order_qty_total += o_qty
        if i_qty is not None:
            invoice_qty_total += i_qty
        received_qty_total += recv_qty

        if first_order_uom is None:
            first_order_uom = _norm_uom(order.uom)
        if first_recv_uom is None:
            first_recv_uom = _norm_uom(recv_uom)
        if first_inv_uom is None:
            first_inv_uom = _norm_uom(inv.uom)

        line_status: LineStatus = "match"
        q_var = Decimal("0")
        p_var = Decimal("0")

        missing = o_qty is None or i_qty is None
        if missing:
            any_missing_qty = True
            line_status = "missing_qty"
            any_qty = True

        ou = _norm_uom(order.uom)
        iu = _norm_uom(inv.uom)
        ru = _norm_uom(recv_uom)
        if line_status == "match":
            uoms = [u for u in (ou, iu) if u]
            if require_receipt and receipt_present and ru:
                uoms.append(ru)
            if len(set(uoms)) > 1:
                line_status = "uom_mismatch"
                any_uom = True
                any_qty = True

        if not missing and i_qty is not None:
            compare_recv = recv_qty if (require_receipt and receipt_present) else (o_qty or Decimal("0"))
            if require_receipt and receipt_present:
                q_var = (i_qty - recv_qty) * i_unit
            else:
                # Two-way: compare invoice qty to order qty for value display; over-bill vs order.
                q_var = (i_qty - (o_qty or Decimal("0"))) * i_unit
                compare_recv = o_qty or Decimal("0")
            p_var = (i_unit - o_unit) * i_qty
            if p_var != 0:
                any_price = True
                if line_status == "match":
                    line_status = "price_variance"
            over = False
            if require_receipt and receipt_present:
                over = _qty_over_billing(i_qty, recv_qty, tolerance_pct=qty_tolerance_pct)
            else:
                over = _qty_over_billing(i_qty, compare_recv, tolerance_pct=qty_tolerance_pct)
            if over and line_status in ("match", "price_variance"):
                if line_status == "match":
                    line_status = "qty_variance"
                any_qty = True
            elif over:
                any_qty = True

        qty_var_total += q_var
        price_var_total += p_var

        results.append(
            LineMatchResult(
                status=line_status,
                description=inv.description or order.description,
                sku=inv.sku or order.sku,
                order_qty=float(o_qty) if o_qty is not None else None,
                order_uom=_norm_uom(order.uom),
                order_unit_price=_round2(o_unit) if order.unit_price is not None or o_unit else None,
                received_qty=float(recv_qty) if require_receipt else None,
                received_uom=_norm_uom(recv_uom) if require_receipt else None,
                invoice_qty=float(i_qty) if i_qty is not None else None,
                invoice_uom=_norm_uom(inv.uom),
                invoice_unit_price=_round2(i_unit),
                qty_variance_value=_round2(q_var),
                price_variance_value=_round2(p_var),
                order_line_key=order.key,
                invoice_line_key=inv.key,
            )
        )

    for order in leftover_orders:
        o_qty = order.qty
        o_unit = order.unit_price or Decimal("0")
        o_val = resolve_line_value(line_value=order.line_value, unit_price=o_unit, qty=o_qty) or Decimal("0")
        order_value += o_val
        if o_qty is not None:
            order_qty_total += o_qty
        o_key = order.key
        recv_qty = received_qty_by_order_key.get(o_key, Decimal("0")) if o_key is not None else Decimal("0")
        received_qty_total += recv_qty
        results.append(
            LineMatchResult(
                status="order_only",
                description=order.description,
                sku=order.sku,
                order_qty=float(o_qty) if o_qty is not None else None,
                order_uom=_norm_uom(order.uom),
                order_unit_price=_round2(o_unit) if order.unit_price is not None else None,
                received_qty=float(recv_qty) if require_receipt else None,
                received_uom=_norm_uom(received_uom_by_order_key.get(o_key)) if require_receipt and o_key is not None else None,
                order_line_key=order.key,
            )
        )

    for inv in leftover_inv:
        any_unmatched_inv = True
        any_qty = True
        i_qty = inv.qty
        i_unit = inv.unit_price or resolve_unit_price(unit_price=None, line_value=inv.line_value, qty=i_qty) or Decimal("0")
        i_val = resolve_line_value(line_value=inv.line_value, unit_price=i_unit, qty=i_qty) or Decimal("0")
        invoice_value += i_val
        if i_qty is not None:
            invoice_qty_total += i_qty
            # Unmatched invoice line counts as full qty variance at invoice price.
            q_var = i_qty * i_unit
            qty_var_total += q_var
        else:
            any_missing_qty = True
            q_var = Decimal("0")
        results.append(
            LineMatchResult(
                status="unmatched_invoice",
                description=inv.description,
                sku=inv.sku,
                invoice_qty=float(i_qty) if i_qty is not None else None,
                invoice_uom=_norm_uom(inv.uom),
                invoice_unit_price=_round2(i_unit),
                qty_variance_value=_round2(q_var),
                invoice_line_key=inv.key,
            )
        )

    # When invoice has lines but order has none (legacy), treat all invoice as unmatched already done.
    # When both empty: fall back to empty match / no receipt handled below.

    if variance_approved:
        status = "3-Way Match" if require_receipt else "2-Way Match"
    elif require_receipt and not receipt_present:
        status = missing_receipt_status
    elif any_price:
        status = "Price Variance"
    elif any_qty or any_missing_qty or any_uom or any_unmatched_inv:
        status = "Qty Variance"
    else:
        status = "3-Way Match" if require_receipt else "2-Way Match"

    # Two-way display label compatibility: callers may map 2-Way Match → existing statuses.
    if not require_receipt and status == "2-Way Match":
        status = "3-Way Match"

    order_unit_w: float | None = None
    inv_unit_w: float | None = None
    if order_qty_total > 0 and order_value:
        order_unit_w = _round2(order_value / order_qty_total)
    if invoice_qty_total > 0 and invoice_value:
        inv_unit_w = _round2(invoice_value / invoice_qty_total)

    return LineMatchRollup(
        status=status,
        qty_variance_value=_round2(qty_var_total),
        price_variance_value=_round2(price_var_total),
        total_deviation=_round2(qty_var_total + price_var_total),
        order_value=_round2(order_value),
        invoice_value=_round2(invoice_value),
        line_results=results,
        order_qty_total=float(order_qty_total),
        received_qty_total=float(received_qty_total),
        invoice_qty_total=float(invoice_qty_total),
        order_unit_price_weighted=order_unit_w,
        invoice_unit_price_weighted=inv_unit_w,
        order_uom=first_order_uom,
        received_uom=first_recv_uom,
        invoice_uom=first_inv_uom,
    )


def sum_received_by_order_line(
    receipt_rows: list[Any],
    *,
    order_line_id_attr: str = "purchase_order_line_id",
) -> tuple[dict[str | int, Decimal], dict[str | int, str | None]]:
    """Sum receipt/delivery line qtys keyed by linked order line id."""
    qtys: dict[str | int, Decimal] = {}
    uoms: dict[str | int, str | None] = {}
    for row in receipt_rows:
        oid = getattr(row, order_line_id_attr, None)
        if oid is None:
            continue
        q = _as_decimal(getattr(row, "qty", None)) or Decimal("0")
        qtys[oid] = qtys.get(oid, Decimal("0")) + q
        if oid not in uoms:
            uoms[oid] = _norm_uom(getattr(row, "uom", None))
    return qtys, uoms


def header_rollup_from_order_lines(lines: list[Any]) -> tuple[Decimal, Decimal, str | None, str | None]:
    """Return (qty_sum, weighted_unit_price, first_description, first_uom)."""
    qty_sum = Decimal("0")
    value_sum = Decimal("0")
    first_desc: str | None = None
    first_uom: str | None = None
    for line in lines:
        q = _as_decimal(getattr(line, "qty", None))
        up = resolve_unit_price(
            unit_price=getattr(line, "unit_price", None),
            line_value=getattr(line, "line_value", None),
            qty=q,
        )
        val = resolve_line_value(
            line_value=getattr(line, "line_value", None),
            unit_price=up,
            qty=q,
        )
        if q is not None:
            qty_sum += q
        if val is not None:
            value_sum += val
        if first_desc is None and getattr(line, "description", None):
            first_desc = getattr(line, "description", None)
        if first_uom is None and getattr(line, "uom", None):
            first_uom = getattr(line, "uom", None)
    unit = (value_sum / qty_sum) if qty_sum > 0 else Decimal("0")
    return qty_sum, unit, first_desc, first_uom
