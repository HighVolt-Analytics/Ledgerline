"""Three-way match detail for dossier hero view and pipeline checks."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.goods_receipt import GoodsReceipt
from app.models.invoice import Invoice
from app.models.purchase_order import PurchaseOrder
from app.schemas.dossier import DossierMatchSummaryResponse, DossierPipelineCheckResponse
from app.schemas.purchase import ThreeWayMatchResult
from app.services.purchase.purchase_match_service import _invoice_qty_and_price, _latest_grn


def _money(value: float | Decimal | int | None) -> float:
    if value is None:
        return 0.0
    return round(float(value), 2)


def _iso_date(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def build_dossier_match_summary(
    *,
    po_row: PurchaseOrder,
    commercial: Invoice | None,
    match: ThreeWayMatchResult,
    currency: str,
    po_doc: Invoice | None = None,
    grn_doc: Invoice | None = None,
) -> DossierMatchSummaryResponse:
    grn: GoodsReceipt | None = _latest_grn(po_row)
    inv_qty = Decimal("0")
    inv_unit = Decimal("0")
    invoice_no: str | None = None
    if commercial is not None:
        inv_qty, inv_unit, _ = _invoice_qty_and_price(commercial)
        invoice_no = (commercial.invoice_no or "").strip() or None

    po_qty = po_row.po_qty
    po_unit = po_row.po_unit_price
    if (po_qty is None or po_qty <= 0) and po_doc is not None:
        doc_qty, doc_unit, _ = _invoice_qty_and_price(po_doc)
        if doc_qty > 0:
            po_qty = doc_qty
        if doc_unit > 0:
            po_unit = doc_unit

    grn_qty = grn.grn_qty if grn is not None else None
    if grn_qty is None and grn_doc is not None:
        doc_qty, _, _ = _invoice_qty_and_price(grn_doc)
        if doc_qty > 0:
            grn_qty = doc_qty

    total_deviation = _money(match.total_deviation)
    return DossierMatchSummaryResponse(
        status=match.status,
        currency=(currency or "SGD").strip() or "SGD",
        po_number=(po_row.po_number or "").strip() or None,
        po_qty=_money(po_qty) if po_qty is not None else None,
        po_unit_price=_money(po_unit) if po_unit is not None else None,
        po_value=_money(match.po_value),
        po_date=_iso_date(po_row.po_date),
        grn_present=grn is not None or grn_doc is not None,
        grn_qty=_money(grn_qty) if grn_qty is not None else None,
        grn_date=_iso_date(grn.grn_date) if grn is not None else None,
        grn_receiver=(grn.receiver or "").strip() or None if grn is not None else None,
        grn_condition=(grn.condition_note or "").strip() or None if grn is not None else None,
        invoice_no=invoice_no,
        invoice_qty=_money(inv_qty) if commercial is not None else None,
        invoice_unit_price=_money(inv_unit) if commercial is not None else None,
        invoice_value=_money(match.invoice_value),
        invoice_gst=_money(match.invoice_gst),
        invoice_total=_money(match.invoice_total),
        qty_variance_value=_money(match.qty_variance_value),
        price_variance_value=_money(match.price_variance_value),
        total_deviation=total_deviation,
        deviation=total_deviation,
    )


def _audit_money(detail: dict[str, object], key: str) -> float | None:
    raw = detail.get(key)
    if raw is None:
        return None
    try:
        return round(float(raw), 2)
    except (TypeError, ValueError):
        return None


def match_summary_from_audit_detail(
    detail: dict[str, object],
    *,
    currency: str,
) -> DossierMatchSummaryResponse | None:
    """Rebuild match summary from persisted three_way_match_evaluated audit payload."""
    status = str(detail.get("match_status") or detail.get("status") or "").strip()
    if not status:
        return None
    po_value = _audit_money(detail, "po_value")
    if po_value is None:
        return None
    total_deviation = _audit_money(detail, "total_deviation") or 0.0
    return DossierMatchSummaryResponse(
        status=status,
        currency=(currency or "SGD").strip() or "SGD",
        po_number=str(detail.get("po_number") or "").strip() or None,
        po_qty=_audit_money(detail, "po_qty"),
        po_unit_price=_audit_money(detail, "po_unit_price"),
        po_value=po_value,
        po_date=str(detail.get("po_date") or "").strip() or None,
        grn_present=bool(detail.get("grn_present")),
        grn_qty=_audit_money(detail, "grn_qty"),
        grn_date=str(detail.get("grn_date") or "").strip() or None,
        grn_receiver=str(detail.get("grn_receiver") or "").strip() or None,
        grn_condition=str(detail.get("grn_condition") or "").strip() or None,
        invoice_no=str(detail.get("invoice_no") or "").strip() or None,
        invoice_qty=_audit_money(detail, "invoice_qty"),
        invoice_unit_price=_audit_money(detail, "invoice_unit_price"),
        invoice_value=_audit_money(detail, "invoice_value") or 0.0,
        invoice_gst=_audit_money(detail, "invoice_gst") or 0.0,
        invoice_total=_audit_money(detail, "invoice_total") or 0.0,
        qty_variance_value=_audit_money(detail, "qty_variance_value") or 0.0,
        price_variance_value=_audit_money(detail, "price_variance_value") or 0.0,
        total_deviation=total_deviation,
        deviation=total_deviation,
    )


def _fmt_qty(value: float | None) -> str:
    if value is None:
        return "—"
    text = f"{value:g}"
    return text


def _fmt_money(value: float, currency: str) -> str:
    symbol = "$" if currency.upper() in {"AUD", "USD", "NZD", "SGD"} else currency
    return f"{symbol}{value:,.2f}"


def match_checks_from_summary(summary: DossierMatchSummaryResponse) -> list[DossierPipelineCheckResponse]:
    """Structured checks for dossier pipeline match stage."""
    checks: list[DossierPipelineCheckResponse] = []
    currency = summary.currency

    if summary.po_qty is not None:
        qty_parts = [
            f"PO {_fmt_qty(summary.po_qty)}",
            f"GRN {_fmt_qty(summary.grn_qty)}",
            f"Inv {_fmt_qty(summary.invoice_qty)}",
        ]
        qty_actual = " · ".join(qty_parts)
        if summary.grn_qty is None:
            qty_state = "fail" if summary.status == "No GRN" else "pending"
        elif summary.qty_variance_value == 0:
            qty_state = "pass"
        else:
            qty_state = "fail"
        checks.append(
            DossierPipelineCheckResponse(
                id="match-qty",
                label="PO qty vs GRN qty vs invoice qty",
                state=qty_state,
                rule_ref="MATCH",
                expected="Received qty supports invoice qty",
                actual=qty_actual,
            )
        )

    if summary.po_unit_price is not None and summary.invoice_unit_price is not None:
        price_state = "pass" if summary.price_variance_value == 0 else "fail"
        checks.append(
            DossierPipelineCheckResponse(
                id="match-price",
                label="Unit price variance",
                state=price_state,
                rule_ref="MATCH",
                expected=_fmt_money(summary.po_unit_price, currency),
                actual=_fmt_money(summary.invoice_unit_price, currency),
                detail=f"Variance {_fmt_money(summary.price_variance_value, currency)}",
            )
        )

    deviation_state = "pass" if summary.total_deviation == 0 else "fail"
    checks.append(
        DossierPipelineCheckResponse(
            id="match-deviation",
            label="Total deviation",
            state=deviation_state,
            rule_ref="MATCH",
            expected=_fmt_money(0, currency),
            actual=_fmt_money(summary.total_deviation, currency),
        )
    )

    checks.append(
        DossierPipelineCheckResponse(
            id="match-invoice-total",
            label="Invoice subtotal + GST = total",
            state="pass"
            if summary.invoice_value + summary.invoice_gst == summary.invoice_total
            else "fail",
            rule_ref="VR01",
            expected=_fmt_money(summary.invoice_total, currency),
            actual=f"{_fmt_money(summary.invoice_value, currency)} + GST {_fmt_money(summary.invoice_gst, currency)}",
        )
    )

    return checks


def enrich_match_pipeline_step(
    pipeline: list,
    *,
    match_summary: DossierMatchSummaryResponse | None,
    match_log_detail: dict[str, object] | None = None,
) -> list:
    """Attach three-way reconciliation checks to the match pipeline stage."""
    if match_summary is None and match_log_detail:
        match_summary = match_summary_from_audit_detail(
            match_log_detail,
            currency=str(match_log_detail.get("currency") or "SGD"),
        )
    if match_summary is None:
        return pipeline

    checks = match_checks_from_summary(match_summary)
    status = match_summary.status
    if match_summary.total_deviation == 0:
        detail = f"Match · {status} · within tolerance"
    else:
        detail = (
            f"Match · {status} · deviation "
            f"{_fmt_money(match_summary.total_deviation, match_summary.currency)}"
        )

    updated: list = []
    for step in pipeline:
        if step.stage_id != "match":
            updated.append(step)
            continue
        merged_checks = checks
        if step.checks:
            seen = {row.id for row in checks}
            merged_checks = [
                *checks,
                *(row for row in step.checks if row.id not in seen),
            ]
        updated.append(
            step.model_copy(
                update={
                    "checks": merged_checks,
                    "detail": detail if step.detail in ("—", "", None) else step.detail,
                }
            )
        )
    return updated
