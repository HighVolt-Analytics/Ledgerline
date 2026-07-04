"""Execute document-type match policies (3-way, 2-way, reference, shipment, etc.)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.purchase_order import PurchaseOrder
from app.schemas.document_type import DocumentTypeDefinition
from app.services.classification.document_type_catalog import get_document_type_definition
from app.services.classification.document_type_playbook_profile_service import effective_match_policy
from app.services.invoice.invoice_data import InvoiceData
from app.services.purchase.purchase_match_service import (
    _invoice_qty_and_price,
    _latest_grn,
    _round2,
    compute_three_way_match,
    load_purchase_order_for_invoice,
)

PRICE_MATCH_PCT = Decimal("0.02")
PRICE_MATCH_CAP_AUD = Decimal("100")

_REFERENCE_FIELD_KEYS = (
    "original_invoice",
    "original_invoice_no",
    "reference_invoice",
    "reference_invoice_no",
    "credit_note_reference",
    "related_invoice",
    "invoice_reference",
)

_REFERENCE_TEXT = re.compile(
    r"(?i)(?:original|reference|related|credit(?:\s+note)?\s+for)\s+"
    r"(?:invoice|inv\.?)\s*(?:no\.?|#)?\s*([A-Z0-9][A-Z0-9/_-]{2,})"
)

_SHIPMENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:AWB|MAWB|HAWB)[\s#:/-]*([A-Z0-9-]{8,})", re.I),
    re.compile(r"\b(?:B/L|BL|bill\s+of\s+lading)[\s#:/-]*([A-Z0-9-]{6,})", re.I),
    re.compile(r"\bcontainer[\s#:/-]*([A-Z]{4}\d{7})\b", re.I),
    re.compile(r"\b(?:shipment|consignment)[\s#:/-]*([A-Z0-9-]{6,})", re.I),
]

_TERMINAL_SKIP = {
    InvoiceStatus.DUPLICATE_SKIPPED,
    InvoiceStatus.REJECTED,
}


@dataclass(frozen=True)
class DocumentMatchOutcome:
    passed: bool
    status: str
    message: str
    match_mode: str
    detail: dict[str, object]


def resolve_match_mode(
    *,
    document_type_code: str | None,
    document_types: list[DocumentTypeDefinition] | None = None,
    tenant_id: int | None = None,
    definition: DocumentTypeDefinition | None = None,
) -> str:
    if definition is not None:
        return effective_match_policy(definition).mode
    code = (document_type_code or "").strip().upper()
    if not code:
        return "three_way_po_grn"
    row = get_document_type_definition(code, document_types=document_types, tenant_id=tenant_id)
    if row is None:
        return "three_way_po_grn"
    return effective_match_policy(row).mode


def is_clean_match_message(message: str, *, match_mode: str = "") -> bool:
    token = (message or "").strip().lower()
    if not token:
        return False
    clean_markers = (
        "3-way match",
        "2-way match",
        "reference match",
        "shipment match",
        "receipt match",
        "matched",
        "full_match",
    )
    if any(marker in token for marker in clean_markers):
        return True
    if match_mode == "none":
        return "not required" in token or "skipped" in token
    return token in {"3-way match", "2-way match", "reference match", "shipment match", "receipt match"}


def _price_variance_exceeds_tolerance(
    *,
    price_variance: float,
    po_unit: float,
    po_qty: float,
) -> bool:
    if price_variance == 0:
        return False
    if po_unit <= 0:
        return abs(price_variance) > float(PRICE_MATCH_CAP_AUD)
    qty_basis = max(po_qty, 1.0)
    pct = abs(price_variance) / (po_unit * qty_basis)
    return pct > float(PRICE_MATCH_PCT) and abs(Decimal(str(price_variance))) > PRICE_MATCH_CAP_AUD


def _extract_reference_invoice_numbers(
    data: InvoiceData,
    invoice: Invoice | None,
) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()

    def add(raw: str | None) -> None:
        token = (raw or "").strip().upper()
        if not token or token in seen:
            return
        current = (invoice.invoice_no if invoice else None) or data.invoice_no or ""
        if token == current.strip().upper():
            return
        seen.add(token)
        refs.append(token)

    for key in _REFERENCE_FIELD_KEYS:
        value = data.raw_fields.get(key)
        if isinstance(value, str):
            add(value)

    text = (data.document_text or "").strip()
    if text:
        for match in _REFERENCE_TEXT.finditer(text):
            add(match.group(1))

    return refs


def _shipment_identifiers(data: InvoiceData) -> list[str]:
    text = (data.document_text or "").strip()
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for pattern in _SHIPMENT_PATTERNS:
        for match in pattern.finditer(text):
            token = match.group(1).strip().upper()
            if token and token not in seen:
                seen.add(token)
                found.append(token)
    return found


def _three_way_outcome(match_mode: str, match) -> DocumentMatchOutcome:
    status = match.status
    passed = status == "3-Way Match"
    return DocumentMatchOutcome(
        passed=passed,
        status=status,
        message=status if passed else f"3-way match exception: {status}",
        match_mode=match_mode,
        detail={
            "qty_variance_value": match.qty_variance_value,
            "price_variance_value": match.price_variance_value,
            "total_deviation": match.total_deviation,
        },
    )


def compute_two_way_po_match(po: PurchaseOrder, inv: Invoice) -> DocumentMatchOutcome:
    inv_qty, inv_unit, _gst = _invoice_qty_and_price(inv)
    po_qty = float(po.po_qty)
    po_unit = float(po.po_unit_price)
    inv_qty_f = float(inv_qty)
    inv_unit_f = float(inv_unit)

    if po.variance_approved:
        return DocumentMatchOutcome(
            passed=True,
            status="2-Way Match",
            message="2-Way Match",
            match_mode="two_way_po_ses",
            detail={"variance_approved": True},
        )

    price_variance = _round2((inv_unit_f - po_unit) * inv_qty_f)
    if _price_variance_exceeds_tolerance(
        price_variance=price_variance,
        po_unit=po_unit,
        po_qty=po_qty,
    ):
        return DocumentMatchOutcome(
            passed=False,
            status="Price Variance",
            message=f"Price variance {price_variance} exceeds tolerance",
            match_mode="two_way_po_ses",
            detail={"price_variance_value": price_variance},
        )

    if inv_qty_f > po_qty:
        return DocumentMatchOutcome(
            passed=False,
            status="Qty Variance",
            message="Qty over-billing — invoice qty exceeds PO (0% tolerance)",
            match_mode="two_way_po_ses",
            detail={"invoice_qty": inv_qty_f, "po_qty": po_qty},
        )

    inv_total = float(inv.subtotal or inv.total or Decimal("0"))
    po_value = po_qty * po_unit
    if inv_total > 0 and po_value > 0 and inv_total > po_value * 1.02 + float(PRICE_MATCH_CAP_AUD):
        return DocumentMatchOutcome(
            passed=False,
            status="Amount Variance",
            message="Invoice amount exceeds PO value beyond tolerance",
            match_mode="two_way_po_ses",
            detail={"invoice_total": inv_total, "po_value": po_value},
        )

    return DocumentMatchOutcome(
        passed=True,
        status="2-Way Match",
        message="2-Way Match",
        match_mode="two_way_po_ses",
        detail={"price_variance_value": price_variance},
    )


def compute_receipt_line_match(po: PurchaseOrder, inv: Invoice) -> DocumentMatchOutcome:
    grn = _latest_grn(po)
    inv_qty, inv_unit, _gst = _invoice_qty_and_price(inv)
    inv_qty_f = float(inv_qty)

    if not inv.line_items:
        return DocumentMatchOutcome(
            passed=False,
            status="No lines",
            message="Receipt match requires invoice line items",
            match_mode="receipt_line",
            detail={},
        )

    missing_qty = [idx + 1 for idx, line in enumerate(inv.line_items) if line.qty is None]
    if missing_qty:
        return DocumentMatchOutcome(
            passed=False,
            status="Line qty missing",
            message=f"Line quantities required for receipt match (lines {missing_qty[:5]})",
            match_mode="receipt_line",
            detail={"missing_line_numbers": missing_qty[:10]},
        )

    if grn is None:
        return DocumentMatchOutcome(
            passed=False,
            status="No GRN",
            message="Goods receipt required for receipt-line match",
            match_mode="receipt_line",
            detail={},
        )

    grn_qty = float(grn.grn_qty)
    if inv_qty_f > grn_qty:
        return DocumentMatchOutcome(
            passed=False,
            status="Qty Variance",
            message="Receipt-line qty exceeds GRN received quantity",
            match_mode="receipt_line",
            detail={"invoice_qty": inv_qty_f, "grn_qty": grn_qty},
        )

    return DocumentMatchOutcome(
        passed=True,
        status="Receipt Match",
        message="Receipt Match",
        match_mode="receipt_line",
        detail={"invoice_qty": inv_qty_f, "grn_qty": grn_qty},
    )


async def _find_reference_invoice(
    session: AsyncSession,
    *,
    tenant_id: int,
    reference_no: str,
    exclude_invoice_id: int | None,
    vendor_hint: str | None,
) -> Invoice | None:
    stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.invoice_no.ilike(reference_no),
            Invoice.status.not_in(_TERMIN_SKIP),
        )
        .limit(5)
    )
    if exclude_invoice_id is not None:
        stmt = stmt.where(Invoice.id != exclude_invoice_id)
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return None
    if not vendor_hint:
        return rows[0]
    hint = vendor_hint.strip().lower()
    for row in rows:
        if (row.vendor or "").strip().lower() == hint:
            return row
    return rows[0]


async def execute_document_match(
    match_mode: str,
    *,
    session: AsyncSession,
    tenant_id: int,
    invoice: Invoice,
    data: InvoiceData,
) -> DocumentMatchOutcome:
    mode = (match_mode or "none").strip().lower()

    if mode == "none":
        return DocumentMatchOutcome(
            passed=True,
            status="Skipped",
            message="Match not required for this document type",
            match_mode=mode,
            detail={},
        )

    if mode == "subledger_reconcile":
        return DocumentMatchOutcome(
            passed=True,
            status="Manual reconcile",
            message="Subledger reconciliation — manual step outside automated match",
            match_mode=mode,
            detail={},
        )

    if mode == "reference_invoice":
        refs = _extract_reference_invoice_numbers(data, invoice)
        if not refs:
            return DocumentMatchOutcome(
                passed=False,
                status="No reference",
                message="Reference invoice number not found on document",
                match_mode=mode,
                detail={},
            )
        vendor_hint = (data.vendor or invoice.vendor or "").strip() or None
        for ref in refs:
            original = await _find_reference_invoice(
                session,
                tenant_id=tenant_id,
                reference_no=ref,
                exclude_invoice_id=invoice.id,
                vendor_hint=vendor_hint,
            )
            if original is None:
                continue
            credit_total = abs(float(invoice.total or data.total or Decimal("0")))
            original_total = abs(float(original.total or Decimal("0")))
            if credit_total > 0 and original_total > 0 and credit_total > original_total * 1.05:
                return DocumentMatchOutcome(
                    passed=False,
                    status="Amount exceeds original",
                    message=f"Amount exceeds original invoice {ref}",
                    match_mode=mode,
                    detail={"reference": ref, "original_total": original_total},
                )
            return DocumentMatchOutcome(
                passed=True,
                status="Reference Match",
                message=f"Reference Match · {ref}",
                match_mode=mode,
                detail={"reference_invoice_id": original.id, "reference": ref},
            )
        return DocumentMatchOutcome(
            passed=False,
            status="Not found",
            message=f"Original invoice not found ({', '.join(refs[:3])})",
            match_mode=mode,
            detail={"references": refs[:5]},
        )

    if mode == "shipment":
        identifiers = _shipment_identifiers(data)
        po_ref = (data.po_reference or invoice.po_reference or "").strip()
        po: PurchaseOrder | None = None
        if po_ref:
            po = await load_purchase_order_for_invoice(session, invoice)
        if identifiers:
            detail: dict[str, object] = {"shipment_refs": identifiers[:5]}
            if po is not None:
                detail["po_number"] = po.po_number
            elif po_ref:
                return DocumentMatchOutcome(
                    passed=False,
                    status="PO not found",
                    message=f"PO {po_ref} not found for shipment match",
                    match_mode=mode,
                    detail={"shipment_refs": identifiers[:5]},
                )
            return DocumentMatchOutcome(
                passed=True,
                status="Shipment Match",
                message=f"Shipment Match · {identifiers[0]}",
                match_mode=mode,
                detail=detail,
            )
        if po is not None:
            return DocumentMatchOutcome(
                passed=True,
                status="Shipment Match",
                message=f"Shipment Match · PO {po.po_number}",
                match_mode=mode,
                detail={"po_number": po.po_number},
            )
        return DocumentMatchOutcome(
            passed=False,
            status="No shipment ref",
            message="Shipment match requires AWB/BL/container reference or PO link",
            match_mode=mode,
            detail={},
        )

    if mode in {"three_way_so_dn", "two_way_dn_invoice"}:
        from app.services.sales.sales_match_service import execute_ar_document_match

        result = await execute_ar_document_match(mode, session=session, invoice=invoice)
        return result  # type: ignore[return-value]

    po = await load_purchase_order_for_invoice(session, invoice)
    po_ref = (data.po_reference or invoice.po_reference or "").strip()
    if not po_ref:
        return DocumentMatchOutcome(
            passed=True,
            status="Skipped",
            message="No PO reference — match skipped",
            match_mode=mode,
            detail={},
        )
    if po is None:
        return DocumentMatchOutcome(
            passed=False,
            status="PO not found",
            message=f"PO {po_ref} not found for match",
            match_mode=mode,
            detail={},
        )

    if mode == "two_way_po_ses":
        return compute_two_way_po_match(po, invoice)

    if mode == "receipt_line":
        return compute_receipt_line_match(po, invoice)

    # Default: three_way_po_grn
    match = compute_three_way_match(po, invoice)
    if match.status == "No GRN":
        return DocumentMatchOutcome(
            passed=False,
            status="No GRN",
            message="GRN required before invoice can match PO",
            match_mode="three_way_po_grn",
            detail={},
        )
    if match.status == "Qty Variance" and match.qty_variance_value > 0:
        return DocumentMatchOutcome(
            passed=False,
            status="Qty Variance",
            message="Qty over-billing — invoice qty exceeds GRN (0% tolerance)",
            match_mode="three_way_po_grn",
            detail={"qty_variance_value": match.qty_variance_value},
        )
    po_unit = float(po.po_unit_price)
    if po_unit > 0 and _price_variance_exceeds_tolerance(
        price_variance=match.price_variance_value,
        po_unit=po_unit,
        po_qty=float(po.po_qty),
    ):
        return DocumentMatchOutcome(
            passed=False,
            status="Price Variance",
            message=f"Price variance {match.price_variance_value} exceeds tolerance",
            match_mode="three_way_po_grn",
            detail={"price_variance_value": match.price_variance_value},
        )
    if match.status in {"Price Variance", "Routed for Approval"}:
        return _three_way_outcome("three_way_po_grn", match)
    return DocumentMatchOutcome(
        passed=True,
        status=match.status,
        message=match.status,
        match_mode="three_way_po_grn",
        detail={
            "qty_variance_value": match.qty_variance_value,
            "price_variance_value": match.price_variance_value,
        },
    )


async def run_document_match_validation(
    data: InvoiceData,
    session: AsyncSession,
    *,
    invoice: Invoice | None,
    tenant_id: int,
    document_type_code: str | None = None,
    document_types: list[DocumentTypeDefinition] | None = None,
) -> DocumentMatchOutcome:
    if invoice is None:
        return DocumentMatchOutcome(
            passed=True,
            status="Deferred",
            message="Match deferred (no invoice context)",
            match_mode="none",
            detail={},
        )

    match_mode = resolve_match_mode(
        document_type_code=document_type_code or invoice.document_type_code,
        document_types=document_types,
        tenant_id=tenant_id,
    )
    return await execute_document_match(
        match_mode,
        session=session,
        tenant_id=tenant_id,
        invoice=invoice,
        data=data,
    )
