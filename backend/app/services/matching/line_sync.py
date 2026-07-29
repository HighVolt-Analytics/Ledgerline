"""Populate order/receipt lines from invoice line_items and roll up headers."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import attributes

from app.models.delivery_note import DeliveryNote
from app.models.delivery_note_line import DeliveryNoteLine
from app.models.goods_receipt import GoodsReceipt
from app.models.goods_receipt_line import GoodsReceiptLine
from app.models.invoice import Invoice
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_line import PurchaseOrderLine
from app.models.sales_order import SalesOrder
from app.models.sales_order_line import SalesOrderLine
from app.services.matching.line_match_engine import (
    MatchLineInput,
    header_rollup_from_order_lines,
    line_input_from_invoice_item,
    line_input_from_order_line,
    pair_order_to_invoice,
    resolve_line_value,
    resolve_unit_price,
)


def _collection_loaded(obj: Any, attr: str) -> bool:
    """True when relationship is already in memory (safe to iterate/clear)."""
    try:
        return attr not in sa_inspect(obj).unloaded
    except Exception:
        return True


def _safe_clear_collection(obj: Any, attr: str) -> None:
    """Clear a one-to-many without lazy IO (MissingGreenlet after flush on new rows)."""
    if not _collection_loaded(obj, attr):
        attributes.set_committed_value(obj, attr, [])
        return
    getattr(obj, attr).clear()


def _safe_collection_rows(obj: Any, attr: str) -> list[Any]:
    if not _collection_loaded(obj, attr):
        return []
    return list(getattr(obj, attr) or [])


def _invoice_lines_sorted(invoice: Invoice) -> list[Any]:
    # Async-safe: never trigger lazy IO on unloaded line_items.
    rows = _safe_collection_rows(invoice, "line_items")
    return sorted(rows, key=lambda r: getattr(r, "id", 0) or 0)


def replace_po_lines_from_invoice(po: PurchaseOrder, invoice: Invoice) -> None:
    """Replace PO lines from invoice line_items and roll up header fields."""
    _safe_clear_collection(po, "lines")
    for idx, item in enumerate(_invoice_lines_sorted(invoice), start=1):
        qty = item.qty
        unit = resolve_unit_price(unit_price=item.unit_price, amount=item.amount, qty=qty)
        value = resolve_line_value(amount=item.amount, unit_price=unit, qty=qty)
        po.lines.append(
            PurchaseOrderLine(
                tenant_id=po.tenant_id,
                line_no=idx,
                description=item.description,
                sku=item.sku,
                qty=qty,
                uom=item.uom,
                unit_price=unit,
                line_value=value,
            )
        )
    apply_po_header_rollup(po)


def ensure_po_lines(po: PurchaseOrder) -> None:
    """If PO has no lines, synthesize one from header (legacy rows)."""
    rows = _safe_collection_rows(po, "lines")
    if rows:
        return
    if not _collection_loaded(po, "lines"):
        attributes.set_committed_value(po, "lines", [])
    po.lines.append(
        PurchaseOrderLine(
            tenant_id=po.tenant_id,
            line_no=1,
            description=po.item,
            qty=po.po_qty,
            uom=po.po_uom,
            unit_price=po.po_unit_price,
            line_value=(po.po_qty or Decimal("0")) * (po.po_unit_price or Decimal("0")),
        )
    )


def apply_po_header_rollup(po: PurchaseOrder) -> None:
    qty, unit, desc, uom = header_rollup_from_order_lines(_safe_collection_rows(po, "lines"))
    po.po_qty = qty if qty > 0 else Decimal("0")
    po.po_unit_price = unit
    if desc:
        po.item = desc[:255] if len(desc) > 255 else desc
    if uom:
        po.po_uom = uom


def replace_so_lines_from_invoice(so: SalesOrder, invoice: Invoice) -> None:
    _safe_clear_collection(so, "lines")
    for idx, item in enumerate(_invoice_lines_sorted(invoice), start=1):
        qty = item.qty
        unit = resolve_unit_price(unit_price=item.unit_price, amount=item.amount, qty=qty)
        value = resolve_line_value(amount=item.amount, unit_price=unit, qty=qty)
        so.lines.append(
            SalesOrderLine(
                tenant_id=so.tenant_id,
                line_no=idx,
                description=item.description,
                sku=item.sku,
                qty=qty,
                uom=item.uom,
                unit_price=unit,
                line_value=value,
            )
        )
    apply_so_header_rollup(so)


def ensure_so_lines(so: SalesOrder) -> None:
    rows = _safe_collection_rows(so, "lines")
    if rows:
        return
    if not _collection_loaded(so, "lines"):
        attributes.set_committed_value(so, "lines", [])
    so.lines.append(
        SalesOrderLine(
            tenant_id=so.tenant_id,
            line_no=1,
            description=so.item,
            qty=so.so_qty,
            uom=so.so_uom,
            unit_price=so.so_unit_price,
            line_value=(so.so_qty or Decimal("0")) * (so.so_unit_price or Decimal("0")),
        )
    )


def apply_so_header_rollup(so: SalesOrder) -> None:
    qty, unit, desc, uom = header_rollup_from_order_lines(_safe_collection_rows(so, "lines"))
    so.so_qty = qty if qty > 0 else Decimal("0")
    so.so_unit_price = unit
    if desc:
        so.item = desc[:255] if len(desc) > 255 else desc
    if uom:
        so.so_uom = uom


def populate_grn_lines_from_invoice(
    grn: GoodsReceipt,
    *,
    po: PurchaseOrder,
    invoice: Invoice | None = None,
    fallback_qty: Decimal | None = None,
) -> None:
    """Create GRN lines from invoice lines (or a single fallback qty) and link to PO lines."""
    ensure_po_lines(po)
    _safe_clear_collection(grn, "lines")
    po_lines = _safe_collection_rows(po, "lines")
    order_inputs = [line_input_from_order_line(ln) for ln in po_lines]

    inv_rows = _safe_collection_rows(invoice, "line_items") if invoice is not None else []
    if inv_rows:
        inv_inputs = [
            line_input_from_invoice_item(item, key=i)
            for i, item in enumerate(_invoice_lines_sorted(invoice))
        ]
        paired, _leftover_orders, leftover_inv = pair_order_to_invoice(order_inputs, inv_inputs)
        for order, inv in paired:
            pol = None
            for candidate in po_lines:
                cin = line_input_from_order_line(candidate)
                if cin.key == order.key or (
                    cin.sku and order.sku and str(cin.sku).upper() == str(order.sku).upper()
                ) or ((cin.description or "") == (order.description or "")):
                    pol = candidate
                    break
            grn.lines.append(
                GoodsReceiptLine(
                    tenant_id=grn.tenant_id,
                    purchase_order_line_id=pol.id if pol is not None and pol.id else None,
                    description=inv.description or (pol.description if pol else None),
                    sku=inv.sku or (pol.sku if pol else None),
                    qty=inv.qty,
                    uom=inv.uom or (pol.uom if pol else None),
                )
            )
        for inv in leftover_inv:
            grn.lines.append(
                GoodsReceiptLine(
                    tenant_id=grn.tenant_id,
                    purchase_order_line_id=None,
                    description=inv.description,
                    sku=inv.sku,
                    qty=inv.qty,
                    uom=inv.uom,
                )
            )
    else:
        qty = fallback_qty if fallback_qty is not None else grn.grn_qty
        first = po_lines[0] if po_lines else None
        grn.lines.append(
            GoodsReceiptLine(
                tenant_id=grn.tenant_id,
                purchase_order_line_id=first.id if first is not None and first.id else None,
                description=first.description if first else None,
                sku=first.sku if first else None,
                qty=qty,
                uom=grn.grn_uom or (first.uom if first else None),
            )
        )

    # Rollup GRN header qty from lines
    total = Decimal("0")
    for gl in _safe_collection_rows(grn, "lines"):
        if gl.qty is not None:
            total += gl.qty
    if total > 0:
        grn.grn_qty = total


def populate_dn_lines_from_invoice(
    dn: DeliveryNote,
    *,
    so: SalesOrder,
    invoice: Invoice | None = None,
    fallback_qty: Decimal | None = None,
) -> None:
    ensure_so_lines(so)
    _safe_clear_collection(dn, "lines")
    so_lines = _safe_collection_rows(so, "lines")

    inv_rows = _safe_collection_rows(invoice, "line_items") if invoice is not None else []
    if inv_rows:
        order_inputs = [line_input_from_order_line(ln) for ln in so_lines]
        inv_inputs = [
            line_input_from_invoice_item(item, key=i)
            for i, item in enumerate(_invoice_lines_sorted(invoice))
        ]
        paired, _lo, leftover_inv = pair_order_to_invoice(order_inputs, inv_inputs)
        for order, inv in paired:
            sol = None
            for candidate in so_lines:
                cin = line_input_from_order_line(candidate)
                if cin.key == order.key or (
                    cin.sku and order.sku and str(cin.sku).upper() == str(order.sku).upper()
                ) or ((cin.description or "") == (order.description or "")):
                    sol = candidate
                    break
            dn.lines.append(
                DeliveryNoteLine(
                    tenant_id=dn.tenant_id,
                    sales_order_line_id=sol.id if sol is not None and sol.id else None,
                    description=inv.description or (sol.description if sol else None),
                    sku=inv.sku or (sol.sku if sol else None),
                    qty=inv.qty,
                    uom=inv.uom or (sol.uom if sol else None),
                )
            )
        for inv in leftover_inv:
            dn.lines.append(
                DeliveryNoteLine(
                    tenant_id=dn.tenant_id,
                    sales_order_line_id=None,
                    description=inv.description,
                    sku=inv.sku,
                    qty=inv.qty,
                    uom=inv.uom,
                )
            )
    else:
        qty = fallback_qty if fallback_qty is not None else dn.dn_qty
        first = so_lines[0] if so_lines else None
        dn.lines.append(
            DeliveryNoteLine(
                tenant_id=dn.tenant_id,
                sales_order_line_id=first.id if first is not None and first.id else None,
                description=first.description if first else None,
                sku=first.sku if first else None,
                qty=qty,
                uom=dn.dn_uom or (first.uom if first else None),
            )
        )

    total = Decimal("0")
    for dl in _safe_collection_rows(dn, "lines"):
        if dl.qty is not None:
            total += dl.qty
    if total > 0:
        dn.dn_qty = total


def order_match_inputs_from_po(po: PurchaseOrder) -> list[MatchLineInput]:
    ensure_po_lines(po)
    return [line_input_from_order_line(ln) for ln in _safe_collection_rows(po, "lines")]


def order_match_inputs_from_so(so: SalesOrder) -> list[MatchLineInput]:
    ensure_so_lines(so)
    return [line_input_from_order_line(ln) for ln in _safe_collection_rows(so, "lines")]


def invoice_match_inputs(invoice: Invoice | None) -> list[MatchLineInput]:
    if invoice is None:
        return []
    return [
        line_input_from_invoice_item(item)
        for item in _invoice_lines_sorted(invoice)
    ]
