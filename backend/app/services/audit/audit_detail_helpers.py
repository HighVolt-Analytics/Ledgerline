"""Structured audit detail payloads for management-page audit trails."""

from __future__ import annotations

import re
from typing import Any

from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice
from app.models.purchase_order import PurchaseOrder
from app.schemas.purchase import ThreeWayMatchResult
from app.services.rule_book.validator import ValidationResult

_ERROR_CODE_RE = re.compile(r"ErrorCode[:\s>]+(\w+)", re.IGNORECASE)


def truncate_audit_error(text: str | None, *, max_len: int = 160) -> str:
    """Single-line, CSV-safe error text for auditor exports."""
    if not text or not str(text).strip():
        return ""
    collapsed = re.sub(r"\s+", " ", str(text).strip())
    code_match = _ERROR_CODE_RE.search(collapsed)
    if code_match:
        code = code_match.group(1)
        short = collapsed[:80].strip()
        if len(short) > max_len:
            short = short[: max_len - 3] + "..."
        return f"ErrorCode: {code} — {short}" if short else f"ErrorCode: {code}"
    if len(collapsed) <= max_len:
        return collapsed
    return collapsed[: max_len - 3] + "..."


def invoice_snapshot_detail(invoice: Invoice) -> dict[str, Any]:
    """Point-in-time invoice fields stamped into audit detail at write time."""
    doc_type = (invoice.purchase_document_type or "").strip().lower()
    po_ref = (invoice.po_reference or "").strip()
    invoice_no = (invoice.invoice_no or "").strip()
    if not invoice_no and doc_type in ("po", "grn") and po_ref:
        invoice_no = f"{doc_type.upper()}-{po_ref}"

    amount: float | None = None
    if invoice.total is not None:
        amount = float(invoice.total)
    elif invoice.subtotal is not None:
        amount = float(invoice.subtotal)

    snapshot: dict[str, Any] = {}
    if invoice.status is not None:
        snapshot["document_status"] = invoice.status.value
    if invoice.evaluation_status:
        snapshot["evaluation_status"] = invoice.evaluation_status
    if invoice.route_target:
        snapshot["route_target"] = invoice.route_target
    if invoice_no:
        snapshot["invoice_no"] = invoice_no
    if invoice.vendor:
        snapshot["vendor_name"] = invoice.vendor
    if po_ref:
        snapshot["po_number"] = po_ref
    if amount is not None:
        snapshot["amount"] = amount
    if invoice.account_name:
        snapshot["ledger"] = invoice.account_name
    if invoice.vendor_confidence is not None:
        snapshot["confidence_score"] = invoice.vendor_confidence
    return snapshot


def _latest_grn(po: PurchaseOrder) -> GoodsReceipt | None:
    if not po.goods_receipts:
        return None
    return max(po.goods_receipts, key=lambda row: row.id)

VR_TE_CHECK_NAMES: dict[str, str] = {
    "VR-TE01": "Employee match",
    "VR-TE02": "Budget",
    "VR-TE03": "Receipt",
    "VR-TE04": "Bank account",
    "VR-TE05": "Employee status",
    "VR-TE06": "Category cap",
    "VR-TE07": "Advance balance",
    "VR-TE08": "GL account budget",
    "VR-TE09": "Duplicate claim",
    "VR-TE10": "Future-dated receipt",
    "VR-TE11": "Currency match",
}

VR_CHECK_NAMES: dict[str, str] = {
    "VR01": "Total = subtotal + GST",
    "VR02": "Duplicate check (multi-layer)",
    "VR03": "Required fields and line items",
    "VR06": "Invoice and due dates",
    "VR08": "GST rate check",
    "VR09": "Line arithmetic",
    "VR11": "Date sanity",
    "VR12": "Vendor master",
    "VR-PB02": "Required supporting documents",
}


def vr_te_results_for_audit(
    results: list[ValidationResult],
    *,
    has_receipt_file: bool,
) -> list[dict[str, object]]:
    """Per-check VR-TE breakdown for validation_passed / validation_failed detail."""
    rows: list[dict[str, object]] = []
    for result in results:
        if not result.rule.startswith("VR-TE"):
            continue
        entry: dict[str, object] = {
            "check_id": result.rule,
            "name": VR_TE_CHECK_NAMES.get(result.rule, result.rule),
            "result": "pass" if result.passed else "fail",
            "reason": result.message,
        }
        if result.rule == "VR-TE03":
            entry["receipt_present"] = has_receipt_file
        rows.append(entry)
    return rows


def vr_core_results_for_audit(results: list[ValidationResult]) -> list[dict[str, object]]:
    """Per-check VR01–VR08 breakdown for validation audit detail."""
    rows: list[dict[str, object]] = []
    for result in results:
        if not result.rule.startswith("VR") or result.rule.startswith("VR-TE"):
            continue
        rows.append(
            {
                "check_id": result.rule,
                "name": VR_CHECK_NAMES.get(result.rule, result.rule),
                "result": "pass" if result.passed else "fail",
                "reason": result.message,
            }
        )
    return rows


def validation_audit_detail(
    results: list[ValidationResult],
    *,
    route_target: str | None,
    has_receipt_file: bool,
) -> dict[str, object] | None:
    detail: dict[str, object] = {}
    route = (route_target or "").strip()
    if route:
        detail["route_target"] = route

    vr_te = vr_te_results_for_audit(results, has_receipt_file=has_receipt_file)
    if vr_te:
        detail["vr_te_results"] = vr_te

    vr_core = vr_core_results_for_audit(results)
    if vr_core:
        detail["vr_results"] = vr_core

    return detail or None


def compute_three_way_audit_status(
    po: PurchaseOrder,
    match: ThreeWayMatchResult,
) -> str:
    """full_match | partial | mismatch for purchase register badges."""
    po_present = po.po_document_id is not None
    grn_present = _latest_grn(po) is not None
    invoice_present = po.invoice_id is not None

    if match.status == "3-Way Match":
        return "full_match"
    if match.status in ("Price Variance", "Qty Variance", "Routed for Approval"):
        if po_present and grn_present and invoice_present:
            return "mismatch"
    if not po_present or not grn_present or not invoice_present:
        return "partial"
    return "partial"


def three_way_match_audit_detail(
    po: PurchaseOrder,
    match: ThreeWayMatchResult,
    status: str,
    *,
    inv: object | None = None,
) -> dict[str, object]:
    from app.services.purchase.purchase_match_service import _invoice_qty_and_price

    grn = _latest_grn(po)
    amounts_reconciled = match.status == "3-Way Match"
    inv_qty: float | None = None
    inv_unit: float | None = None
    invoice_no: str | None = None
    currency = ""
    if inv is not None:
        qty, unit, _ = _invoice_qty_and_price(inv)  # type: ignore[arg-type]
        inv_qty = float(qty)
        inv_unit = float(unit)
        invoice_no = getattr(inv, "invoice_no", None)
        currency = (getattr(inv, "currency", None) or "").strip()
    return {
        "po_present": po.po_document_id is not None,
        "grn_present": grn is not None,
        "invoice_present": po.invoice_id is not None,
        "amounts_reconciled": amounts_reconciled,
        "status": status,
        "match_status": match.status,
        "purchase_order_id": po.id,
        "po_number": po.po_number,
        "po_qty": float(po.po_qty),
        "po_unit_price": float(po.po_unit_price),
        "po_value": match.po_value,
        "po_date": po.po_date.isoformat() if po.po_date else None,
        "grn_qty": float(grn.grn_qty) if grn is not None else None,
        "grn_date": grn.grn_date.isoformat() if grn is not None and grn.grn_date else None,
        "grn_receiver": grn.receiver if grn is not None else None,
        "grn_condition": grn.condition_note if grn is not None else None,
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
