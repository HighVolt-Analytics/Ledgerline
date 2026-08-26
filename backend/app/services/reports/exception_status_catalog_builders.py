"""Claim Status, Policy Exceptions, Invoice Exception, Process Efficiency, and Control Centre."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.models.purchase_order import PurchaseOrder, PurchaseOrderStatus
from app.models.tenant import Tenant
from app.schemas.report_catalog import ReportPreview, ReportPreviewRow
from app.schemas.rule_book_config import (
    TEAM_EXPENSE_KIND_ADVANCE,
    TEAM_EXPENSE_KIND_DIRECT,
    normalize_team_expense_kind,
)
from app.services.approval.approval_quorum_service import (
    progress_from_chain,
    required_count,
)
from app.services.invoice.invoice_evaluation_service import (
    EVAL_PENDING_APPROVAL,
    ROUTE_PURCHASE,
    ROUTE_SALES,
    ROUTE_TEAM,
    ROUTE_VAULT,
    load_posting_config_for_tenant,
)
from app.services.master_data.department_budget_service import (
    build_department_budget_utilization_rows,
)
from app.services.master_data.master_data_service import list_employee_masters
from app.services.purchase.team_expense_spend_service import (
    load_committed_claim_spend_rows,
    period_key_bounds,
    spend_for_tokens,
)
from app.services.purchase.team_expense_validator import (
    has_receipt_attachment,
    resolve_team_expense_employee,
)
from app.services.reports.payables_catalog_builders import build_payment_schedule, last_approval
from app.services.reports.report_catalog import CATALOG_BY_ID, ReportDefinition
from app.services.reports.team_expense_catalog_builders import (
    _invoices_in_range,
    _missing_te_row,
    _te_invoices_in_range,
    build_advance_aging,
)
from app.tenant_settings import tenant_currency

_ZERO = Decimal("0.00")
_POLICY_RULES = frozenset(
    {"VR-TE04", "VR-TE05", "VR-TE08", "VR-TE09", "VR-TE10", "VR-TE11"}
)
_CLAIM_STATUS_COLUMNS = [
    "Claim ID",
    "Employee",
    "Department",
    "Submitted Date",
    "Amount",
    "Current Stage",
    "Current Approver",
    "Age in Stage",
    "Reimbursement Date",
    "Status / Reason",
]
_CLAIM_STATUS_NOTES = (
    "Tracks employee claims from draft/submission through approval and reimbursement. "
    "Age in Stage uses the approval-hold timestamp when present, otherwise submitted date. "
    "Completed stages show 0. Current Approver is the last signer plus remaining pool seats. "
    "Reimbursement Date comes from a scheduled payment row."
)
_EM_DASH = "—"
_PROCESS_EFFICIENCY_NOTES = (
    "Measures speed, automation and operational efficiency across invoice-to-pay. "
    "Straight-through is a proxy: processed invoices with no invoice_fields_updated "
    "event and no approval hold (team_expense_approval_required or invoice_approved). "
    "Manual intervention is the complement. First-pass validation is a proxy: invoices "
    "in the period with no failed validation result and no field edit. Receipt date is "
    "invoices.created_at (ingest), not invoice_date. Target and Cost per invoice have "
    "no data source — shown as -. Current Month / Previous Month follow the selected period."
)
_PROCESS_EFFICIENCY_COLUMNS = [
    "Metric",
    "Current Month",
    "Previous Month",
    "Target",
    "Trend",
    "Definition",
]
_CONTROL_CENTRE_NOTES = (
    "Prioritized action queue. Overdue AP, advances outstanding over 60 days, "
    "budget overruns, policy exceptions, invoice exceptions, and missing expense "
    "receipts. Vendor bank-change before payment and insurance expiry are omitted "
    "until those registers exist. Vendor tax-invoice gaps stay on Missing Documents."
)
_CONTROL_COLUMNS = [
    "Priority",
    "Alert",
    "Module",
    "Amount",
    "Owner",
    "Age / Due",
    "Recommended Action",
    "Status",
]
_PRIORITY_RANK = {"Critical": 0, "High": 1, "Medium": 2}
_MODULE_RANK = {
    "Invoice-to-Pay": 0,
    "Expenses": 1,
    "Budget": 2,
    "Files": 3,
}
_POLICY_ACTIONS = {
    "VR-TE04": "Add employee bank details",
    "VR-TE05": "Review employee status",
    "VR-TE08": "Review GL budget or reduce amount",
    "VR-TE09": "Review possible duplicate claim",
    "VR-TE10": "Correct receipt/invoice date",
    "VR-TE11": "Recode claim currency",
}
_DUP_EVENTS = (
    "fuzzy_duplicate_suspected",
    "duplicate_skipped",
    "duplicate_in_progress",
)
_PO_EVENTS = ("three_way_match_evaluated",)
_INVOICE_EXCEPTION_COLUMNS = [
    "Risk",
    "Exception Type",
    "Invoice ID",
    "Vendor",
    "Amount",
    "Detected On",
    "Reason",
    "Owner",
    "Status",
    "Action",
]
_INVOICE_EXCEPTION_NOTES = (
    "Fraud indicators and validation. Potential Duplicate from VR02 / skipped "
    "duplicate files. PO Mismatch is Purchase invoices with a linked purchase order only. "
    "Bank Detail Change is a bank-change document on an AP invoice."
)
_BANK_CHANGE_TOKENS = (
    "bank_change",
    "bank-change",
    "bank detail",
    "bank_details_change",
    "change of bank",
    "change-of-bank",
)
_AP_SKIP_ROUTES = frozenset({ROUTE_TEAM, ROUTE_SALES, ROUTE_VAULT})
_HOLD_EVENTS = ("team_expense_approval_required", "invoice_approved")
_EDIT_EVENT = "invoice_fields_updated"
_APPROVAL_HOLD_EVENT = "team_expense_approval_required"


def _money(value: Decimal | None) -> str:
    return f"{(value or _ZERO).quantize(Decimal('0.01')):,.2f}"


def _text(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _cell_row(*cells: str, emphasize: bool = False) -> ReportPreviewRow:
    return ReportPreviewRow(cells=[_text(c) for c in cells], emphasize=emphasize)


def _preview(
    definition: ReportDefinition,
    *,
    period_label: str,
    currency: str,
    columns: list[str],
    rows: list[ReportPreviewRow],
    notes: str | None = None,
) -> ReportPreview:
    return ReportPreview(
        report_id=definition.id,
        title=definition.name,
        period_label=period_label,
        currency=currency,
        columns=columns,
        rows=rows,
        empty=len(rows) == 0,
        notes=notes,
    )


def _period_label(start: date, end: date) -> str:
    if start == end:
        return start.isoformat()
    return f"{start.isoformat()} – {end.isoformat()}"


async def _currency(db: AsyncSession, tenant_id: uuid.UUID) -> str:
    tenant = await db.get(Tenant, tenant_id)
    return tenant_currency(tenant)


def _parse_validation_rows(raw: object | None) -> list[dict]:
    if not raw:
        return []
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _failed_rules(invoice: Invoice, allowed: frozenset[str]) -> list[dict]:
    out: list[dict] = []
    for row in _parse_validation_rows(invoice.validation_results):
        rule = str(row.get("rule") or "").strip()
        if rule not in allowed:
            continue
        if row.get("skipped"):
            continue
        if row.get("passed"):
            continue
        out.append(row)
    return out


def _invoice_failed_any_validation(invoice: Invoice) -> bool:
    for row in _parse_validation_rows(invoice.validation_results):
        if row.get("skipped"):
            continue
        if row.get("passed"):
            continue
        return True
    return False


def _is_claim_document(invoice: Invoice) -> bool:
    kind = normalize_team_expense_kind(invoice.team_expense_kind)
    if kind == TEAM_EXPENSE_KIND_ADVANCE or kind == TEAM_EXPENSE_KIND_DIRECT:
        return False
    return True


def _current_stage(invoice: Invoice) -> str:
    eval_status = (invoice.evaluation_status or "").strip().lower()
    if invoice.status == InvoiceStatus.REJECTED:
        return "Rejected"
    if invoice.status == InvoiceStatus.PROCESSED:
        return "Approved"
    if invoice.status == InvoiceStatus.DUPLICATE_SKIPPED:
        return "Duplicate skipped"
    if eval_status == EVAL_PENDING_APPROVAL:
        progress = progress_from_chain(invoice.approval_chain)
        if progress is not None and progress.required >= 2 and progress.recorded >= 1:
            return "Finance Review"
        return "Manager Approval"
    if eval_status:
        return eval_status.replace("_", " ").title()
    status = _text(getattr(invoice.status, "value", invoice.status))
    return status.replace("_", " ").title() if status else ""


def _current_approver_label(invoice: Invoice, tenant_id: uuid.UUID, stage: str) -> str:
    if stage in {"Approved", "Rejected", "Duplicate skipped"}:
        return _EM_DASH
    last_name, _ = last_approval(invoice.approval_chain)
    progress = progress_from_chain(invoice.approval_chain)
    remaining = progress.remaining if progress is not None else required_count(
        tenant_id, "team_expenses"
    )
    pending = (invoice.evaluation_status or "").strip().lower() == EVAL_PENDING_APPROVAL
    if pending and remaining > 0:
        pool = f"awaiting pool ({remaining} remaining)"
        if last_name:
            return f"{last_name}; {pool}"
        return pool
    return last_name or _EM_DASH


def _submitted_on(invoice: Invoice) -> date | None:
    if invoice.invoice_date is not None:
        return invoice.invoice_date
    if isinstance(invoice.created_at, datetime):
        return invoice.created_at.date()
    if isinstance(invoice.created_at, date):
        return invoice.created_at
    return None


def _claim_age_in_stage(
    invoice: Invoice,
    *,
    as_of: date,
    hold: AuditLog | None,
) -> str:
    stage = _current_stage(invoice)
    if stage in {"Approved", "Rejected", "Duplicate skipped"}:
        return "0"
    entered = _as_date(hold.created_at) if hold is not None else _submitted_on(invoice)
    if entered is None:
        return "0"
    return str(max(0, (as_of - entered).days))


def _claim_status_reason(invoice: Invoice, payment: Payment | None) -> str:
    if invoice.status == InvoiceStatus.REJECTED:
        if _failed_rules(invoice, frozenset({"VR-TE03"})):
            return "Missing receipt"
        return "Rejected"
    if payment is not None and (
        payment.status == PaymentStatus.SCHEDULED or payment.scheduled_date is not None
    ):
        return "Scheduled"
    if (invoice.evaluation_status or "").strip().lower() == EVAL_PENDING_APPROVAL:
        return "Pending"
    if invoice.status == InvoiceStatus.PROCESSED:
        return "Approved"
    return _text(getattr(invoice.status, "value", invoice.status)).replace("_", " ").title()


def _reimbursement_date(payment: Payment | None) -> str:
    if payment is None:
        return ""
    if payment.scheduled_date is not None:
        return payment.scheduled_date.isoformat()
    paid = _as_date(payment.paid_date)
    return paid.isoformat() if paid is not None else ""


def _as_date(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


async def _latest_audit_by_invoice(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    invoice_ids: list[int],
    events: tuple[str, ...],
) -> dict[int, AuditLog]:
    if not invoice_ids:
        return {}
    rows = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.tenant_id == tenant_id,
                AuditLog.invoice_id.in_(invoice_ids),
                AuditLog.event.in_(events),
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        )
    ).scalars().all()
    latest: dict[int, AuditLog] = {}
    for row in rows:
        if row.invoice_id is None or row.invoice_id in latest:
            continue
        latest[row.invoice_id] = row
    return latest


def _actor_from_audit(log: AuditLog | None) -> str:
    if log is None:
        return ""
    detail = log.detail if isinstance(log.detail, dict) else {}
    return _text(detail.get("actor_name")) or _text(detail.get("actor_email"))


async def build_claim_status(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    definition: ReportDefinition,
    start: date,
    end: date,
    *,
    as_of: bool = False,
) -> ReportPreview:
    currency = await _currency(db, tenant_id)
    employees = await list_employee_masters(
        db, tenant_id, include_advance_balances=False
    )
    invoices = await _te_invoices_in_range(db, tenant_id, start, end, as_of=as_of)
    invoice_ids = [inv.id for inv in invoices if inv.id is not None]
    hold_logs = await _latest_audit_by_invoice(
        db, tenant_id, invoice_ids, (_APPROVAL_HOLD_EVENT,)
    )
    pay_by_invoice: dict[int, Payment] = {}
    if invoice_ids:
        pay_rows = (
            await db.execute(
                select(Payment)
                .where(
                    Payment.tenant_id == tenant_id,
                    Payment.invoice_id.in_(invoice_ids),
                )
                .order_by(Payment.id.asc())
            )
        ).scalars().all()
        for pay in pay_rows:
            pay_by_invoice[pay.invoice_id] = pay
    rows: list[ReportPreviewRow] = []
    for invoice in invoices:
        if not _is_claim_document(invoice):
            continue
        employee = resolve_team_expense_employee(
            employees,
            employee_email=invoice.employee_email,
            email_sender=invoice.email_sender,
        )
        stage = _current_stage(invoice)
        payment = pay_by_invoice.get(invoice.id) if invoice.id is not None else None
        submitted = _submitted_on(invoice)
        rows.append(
            _cell_row(
                invoice.invoice_no or invoice.document_ref or str(invoice.id),
                employee.name if employee else "",
                (employee.department if employee else "") or "",
                submitted.isoformat() if submitted else "",
                _money(Decimal(str(invoice.total or 0))),
                stage,
                _current_approver_label(invoice, tenant_id, stage),
                _claim_age_in_stage(
                    invoice, as_of=end, hold=hold_logs.get(invoice.id)
                ),
                _reimbursement_date(payment),
                _claim_status_reason(invoice, payment),
            )
        )
    return _preview(
        definition,
        period_label=f"As of {end.isoformat()}" if as_of else _period_label(start, end),
        currency=currency,
        columns=list(_CLAIM_STATUS_COLUMNS),
        rows=rows,
        notes=_CLAIM_STATUS_NOTES,
    )


async def build_policy_exceptions(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    definition: ReportDefinition,
    start: date,
    end: date,
) -> ReportPreview:
    currency = await _currency(db, tenant_id)
    employees = await list_employee_masters(
        db, tenant_id, include_advance_balances=False
    )
    invoices = (
        await db.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.route_target == ROUTE_TEAM,
                Invoice.invoice_date.is_not(None),
                Invoice.invoice_date >= start,
                Invoice.invoice_date <= end,
            )
            .order_by(Invoice.invoice_date, Invoice.id)
        )
    ).scalars().all()
    rows: list[ReportPreviewRow] = []
    for invoice in invoices:
        failures = _failed_rules(invoice, _POLICY_RULES)
        if not failures:
            continue
        employee = resolve_team_expense_employee(
            employees,
            employee_email=invoice.employee_email,
            email_sender=invoice.email_sender,
        )
        evidence = (
            "Receipt on file"
            if has_receipt_attachment(invoice.raw_file_path)
            else "No stored file"
        )
        for fail in failures:
            rule = str(fail.get("rule") or "")
            severity = str(fail.get("severity") or "block")
            risk = "High" if rule in {"VR-TE08", "VR-TE09"} and severity != "warn" else "Medium"
            if rule == "VR-TE08" and severity == "warn":
                risk = "Medium"
            rows.append(
                _cell_row(
                    risk,
                    rule,
                    invoice.invoice_no or str(invoice.id),
                    employee.name if employee else "",
                    invoice.vendor or "",
                    _money(Decimal(str(invoice.total or 0))),
                    invoice.invoice_date.isoformat() if invoice.invoice_date else "",
                    _text(fail.get("message")),
                    evidence,
                    _POLICY_ACTIONS.get(rule, "Review policy exception"),
                )
            )
    return _preview(
        definition,
        period_label=_period_label(start, end),
        currency=currency,
        columns=[
            "Risk",
            "Exception",
            "Claim ID",
            "Employee",
            "Merchant",
            "Amount",
            "Date",
            "Reason",
            "Evidence Status",
            "Recommended Action",
        ],
        rows=rows,
        notes="VR-TE03 receipt failures are listed only on Missing Documents.",
    )


def _invoice_has_vr02(invoice: Invoice) -> bool:
    if invoice.status == InvoiceStatus.DUPLICATE_SKIPPED:
        return True
    if invoice.duplicate_review_suggested:
        return True
    return bool(_failed_rules(invoice, frozenset({"VR02"})))


def _po_is_variance(po: PurchaseOrder) -> bool:
    if po.status == PurchaseOrderStatus.VARIANCE_PENDING:
        return True
    status = (po.three_way_match_status or "").strip().lower()
    return status in {"mismatch", "variance_pending"}


def _po_value(po: PurchaseOrder) -> Decimal:
    return (Decimal(str(po.po_qty or 0)) * Decimal(str(po.po_unit_price or 0))).quantize(
        Decimal("0.01")
    )


def _po_mismatch_reason(invoice: Invoice, po: PurchaseOrder) -> str:
    invoice_amt = Decimal(str(invoice.total or 0))
    po_amt = _po_value(po)
    delta = invoice_amt - po_amt
    if delta > 0:
        return f"Invoice exceeds PO by {_money(delta)}"
    if delta < 0:
        return f"Invoice below PO by {_money(abs(delta))}"
    return f"PO {po.po_number or ''} mismatch".strip()


def _looks_like_bank_change_document(invoice: Invoice) -> bool:
    blob = " ".join(
        part
        for part in (
            invoice.document_type_code,
            invoice.email_attachment_name,
            invoice.purchase_document_type,
        )
        if part
    ).lower().replace("_", " ")
    compact = blob.replace(" ", "").replace("-", "")
    if "bankdetail" in compact or "bankchange" in compact or "changeofbank" in compact:
        return True
    return any(token in blob for token in _BANK_CHANGE_TOKENS)


def _bank_change_reason(invoice: Invoice, payment: Payment | None, detected: str) -> str:
    if payment is not None and payment.scheduled_date is not None:
        detected_on = None
        if detected:
            try:
                detected_on = date.fromisoformat(detected[:10])
            except ValueError:
                detected_on = None
        if detected_on is not None:
            days = (payment.scheduled_date - detected_on).days
            if days == 1:
                return "Bank account changed 1 day before scheduled payment"
            if days > 1:
                return f"Bank account changed {days} days before scheduled payment"
            if days == 0:
                return "Bank account changed on scheduled payment date"
            return "Bank account changed after scheduled payment date"
        return "Bank account changed before scheduled payment"
    return "Bank detail change document"


def _bank_change_status(payment: Payment | None) -> str:
    if payment is None:
        return "Open"
    if payment.status == PaymentStatus.SCHEDULED or payment.scheduled_date is not None:
        return "Blocked"
    return "Open"


async def build_invoice_exception(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    definition: ReportDefinition,
    start: date,
    end: date,
    *,
    as_of: bool = False,
) -> ReportPreview:
    currency = await _currency(db, tenant_id)
    invoices = await _invoices_in_range(
        db, tenant_id, start, end, as_of=as_of, team_only=False
    )
    invoice_ids = [inv.id for inv in invoices if inv.id is not None]
    pos: list[PurchaseOrder] = []
    if invoice_ids:
        pos = list(
            (
                await db.execute(
                    select(PurchaseOrder).where(
                        PurchaseOrder.tenant_id == tenant_id,
                        or_(
                            PurchaseOrder.invoice_id.in_(invoice_ids),
                            PurchaseOrder.po_document_id.in_(invoice_ids),
                        ),
                    )
                )
            ).scalars().all()
        )
    po_by_invoice: dict[int, list[PurchaseOrder]] = defaultdict(list)
    for po in pos:
        if po.invoice_id:
            po_by_invoice[po.invoice_id].append(po)
        if po.po_document_id:
            po_by_invoice[po.po_document_id].append(po)

    payments: dict[int, Payment] = {}
    if invoice_ids:
        pay_rows = (
            await db.execute(
                select(Payment).where(
                    Payment.tenant_id == tenant_id,
                    Payment.invoice_id.in_(invoice_ids),
                )
            )
        ).scalars().all()
        for pay in pay_rows:
            payments[pay.invoice_id] = pay

    dup_logs = await _latest_audit_by_invoice(db, tenant_id, invoice_ids, _DUP_EVENTS)
    po_logs = await _latest_audit_by_invoice(db, tenant_id, invoice_ids, _PO_EVENTS)

    rows: list[ReportPreviewRow] = []
    for invoice in invoices:
        route = (invoice.route_target or "").strip()
        linked = [
            po
            for po in po_by_invoice.get(invoice.id, [])
            if route == ROUTE_PURCHASE
        ]
        dup = _invoice_has_vr02(invoice)
        variance_pos = [po for po in linked if _po_is_variance(po)]
        payment = payments.get(invoice.id) if invoice.id is not None else None
        invoice_detected = invoice.invoice_date.isoformat() if invoice.invoice_date else ""
        ref = invoice.invoice_no or str(invoice.id)
        amount = _money(Decimal(str(invoice.total or 0)))
        vendor = invoice.vendor or ""
        if dup:
            owner = _actor_from_audit(dup_logs.get(invoice.id))
            detected = invoice_detected
            log = dup_logs.get(invoice.id)
            if log is not None:
                detected_on = _as_date(log.created_at)
                if detected_on is not None:
                    detected = detected_on.isoformat()
            rows.append(
                _cell_row(
                    "High",
                    "Potential Duplicate",
                    ref,
                    vendor,
                    amount,
                    detected,
                    "Same amount/vendor and similar invoice number",
                    owner,
                    "Under review",
                    "Compare source document and hash",
                )
            )
        for po in variance_pos:
            owner = _actor_from_audit(po_logs.get(invoice.id))
            rows.append(
                _cell_row(
                    "Medium",
                    "PO Mismatch",
                    ref,
                    vendor,
                    amount,
                    invoice_detected,
                    _po_mismatch_reason(invoice, po),
                    owner,
                    "Open",
                    "Approve variance or request credit",
                )
            )
        if route not in _AP_SKIP_ROUTES and _looks_like_bank_change_document(invoice):
            rows.append(
                _cell_row(
                    "Critical",
                    "Bank Detail Change",
                    ref,
                    vendor,
                    amount,
                    invoice_detected,
                    _bank_change_reason(invoice, payment, invoice_detected),
                    "",
                    _bank_change_status(payment),
                    "Independent bank verification",
                )
            )
    rows.sort(
        key=lambda row: (
            _PRIORITY_RANK.get(row.cells[0], 9) if row.cells else 9,
            row.cells[2].casefold() if len(row.cells) > 2 else "",
        )
    )
    return _preview(
        definition,
        period_label=f"As of {end.isoformat()}" if as_of else _period_label(start, end),
        currency=currency,
        columns=list(_INVOICE_EXCEPTION_COLUMNS),
        rows=rows,
        notes=_INVOICE_EXCEPTION_NOTES,
    )


class _EfficiencySlice(NamedTuple):
    processed: int
    avg_days: Decimal | None
    stp_pct: Decimal | None
    manual_pct: Decimal | None
    first_pass_pct: Decimal | None


async def _process_efficiency_slice(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
) -> _EfficiencySlice:
    invoices = (
        await db.execute(
            select(Invoice).where(
                Invoice.tenant_id == tenant_id,
                Invoice.created_at.is_not(None),
            )
        )
    ).scalars().all()
    invoices = [
        inv
        for inv in invoices
        if (day := _as_date(inv.created_at)) is not None and start <= day <= end
    ]
    processed = [inv for inv in invoices if inv.status == InvoiceStatus.PROCESSED]
    processed_count = len(processed)
    ids = [inv.id for inv in invoices if inv.id is not None]
    events: dict[int, set[str]] = defaultdict(set)
    approved_at: dict[int, datetime] = {}
    if ids:
        logs = (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.invoice_id.in_(ids),
                    AuditLog.event.in_(
                        (_EDIT_EVENT, *_HOLD_EVENTS, "team_expense_auto_approved")
                    ),
                )
            )
        ).scalars().all()
        for log in logs:
            if log.invoice_id is None:
                continue
            events[log.invoice_id].add(log.event)
            if log.event in {"invoice_approved", "team_expense_auto_approved"}:
                if log.created_at is not None and (
                    log.invoice_id not in approved_at
                    or log.created_at < approved_at[log.invoice_id]
                ):
                    approved_at[log.invoice_id] = log.created_at

    delays: list[int] = []
    for inv in invoices:
        stamp = approved_at.get(inv.id)
        if stamp is None or inv.created_at is None:
            continue
        start_day = _as_date(inv.created_at)
        end_day = _as_date(stamp)
        if start_day is None or end_day is None:
            continue
        delays.append(max(0, (end_day - start_day).days))
    avg_days = (
        (Decimal(sum(delays)) / Decimal(len(delays))).quantize(Decimal("0.1"))
        if delays
        else None
    )

    stp = 0
    for inv in processed:
        kinds = events.get(inv.id, set())
        held = bool(kinds & set(_HOLD_EVENTS))
        edited = _EDIT_EVENT in kinds
        if not held and not edited:
            stp += 1
    if processed_count == 0:
        stp_pct = None
        manual_pct = None
    else:
        stp_pct = (Decimal(stp) * Decimal("100") / Decimal(processed_count)).quantize(
            Decimal("0.1")
        )
        manual_pct = (Decimal("100.0") - stp_pct).quantize(Decimal("0.1"))

    if not invoices:
        first_pass_pct = None
    else:
        first_pass = 0
        for inv in invoices:
            kinds = events.get(inv.id, set())
            if _EDIT_EVENT in kinds:
                continue
            if _invoice_failed_any_validation(inv):
                continue
            first_pass += 1
        first_pass_pct = (
            Decimal(first_pass) * Decimal("100") / Decimal(len(invoices))
        ).quantize(Decimal("0.1"))
    return _EfficiencySlice(
        processed_count, avg_days, stp_pct, manual_pct, first_pass_pct
    )


def _count_trend(current: int, previous: int) -> str:
    if current > previous:
        return "Up"
    if current < previous:
        return "Down"
    return "Unchanged"


def _quality_trend(
    current: Decimal | None,
    previous: Decimal | None,
    *,
    lower_is_better: bool,
) -> str:
    if current is None or previous is None:
        return "-"
    if current < previous:
        return "Improving" if lower_is_better else "Worsening"
    if current > previous:
        return "Worsening" if lower_is_better else "Improving"
    return "Unchanged"


def _metric_cell(value: Decimal | int | None, *, pct: bool = False) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return str(value)
    if pct:
        return f"{value}%"
    return f"{value}"


def _efficiency_row(
    name: str,
    current: Decimal | int | None,
    previous: Decimal | int | None,
    *,
    definition: str,
    pct: bool = False,
    lower_is_better: bool | None = None,
) -> ReportPreviewRow:
    if lower_is_better is None:
        trend = _count_trend(int(current or 0), int(previous or 0))
    else:
        trend = _quality_trend(
            current if isinstance(current, Decimal) or current is None else Decimal(current),
            previous if isinstance(previous, Decimal) or previous is None else Decimal(previous),
            lower_is_better=lower_is_better,
        )
    return _cell_row(
        name,
        _metric_cell(current, pct=pct),
        _metric_cell(previous, pct=pct),
        "-",
        trend,
        definition,
    )


async def build_process_efficiency(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    definition: ReportDefinition,
    start: date,
    end: date,
    *,
    prior_start: date,
    prior_end: date,
) -> ReportPreview:
    currency = await _currency(db, tenant_id)
    current = await _process_efficiency_slice(db, tenant_id, start, end)
    prior = await _process_efficiency_slice(db, tenant_id, prior_start, prior_end)
    rows = [
        _efficiency_row(
            "Invoices processed",
            current.processed,
            prior.processed,
            definition="Count of invoices completed",
        ),
        _efficiency_row(
            "Avg receipt-to-approval days",
            current.avg_days,
            prior.avg_days,
            definition="Calendar days from receipt to final approval",
            lower_is_better=True,
        ),
        _efficiency_row(
            "Straight-through processing %",
            current.stp_pct,
            prior.stp_pct,
            definition="No manual intervention",
            pct=True,
            lower_is_better=False,
        ),
        _efficiency_row(
            "Manual intervention %",
            current.manual_pct,
            prior.manual_pct,
            definition="Any human correction / exception touch",
            pct=True,
            lower_is_better=True,
        ),
        _efficiency_row(
            "First-pass validation %",
            current.first_pass_pct,
            prior.first_pass_pct,
            definition="Invoices passing validation first time",
            pct=True,
            lower_is_better=False,
        ),
        _efficiency_row(
            "Cost per invoice",
            None,
            None,
            definition="Estimated AP operating cost / invoices processed",
            lower_is_better=True,
        ),
    ]
    preview = _preview(
        definition,
        period_label=_period_label(start, end),
        currency=currency,
        columns=list(_PROCESS_EFFICIENCY_COLUMNS),
        rows=rows,
        notes=_PROCESS_EFFICIENCY_NOTES,
    )
    return preview.model_copy(update={"empty": False})


def _preview_maps(preview: ReportPreview) -> list[dict[str, str]]:
    cols = preview.columns
    out: list[dict[str, str]] = []
    for row in preview.rows:
        if row.emphasize:
            continue
        mapping: dict[str, str] = {}
        for idx, name in enumerate(cols):
            mapping[name] = row.cells[idx] if idx < len(row.cells) else ""
        out.append(mapping)
    return out


def _parse_money(text: str) -> Decimal:
    cleaned = (text or "").replace(",", "").replace("%", "").strip()
    if not cleaned or cleaned in {"-", "—"}:
        return _ZERO
    try:
        return Decimal(cleaned)
    except Exception:
        return _ZERO


def _parse_int(text: str) -> int | None:
    cleaned = (text or "").replace(",", "").strip()
    if not cleaned or cleaned in {"-", "—"}:
        return None
    try:
        return int(Decimal(cleaned))
    except Exception:
        return None


def _age_due_from_days(days: int | None) -> str:
    if days is None:
        return ""
    if days <= 0:
        return "Today"
    return f"{days} days"


def _age_due_from_date(value: str, as_of: date) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        parsed = date.fromisoformat(raw[:10])
    except ValueError:
        return raw
    return _age_due_from_days((as_of - parsed).days)


def _control_row(
    *,
    priority: str,
    alert: str,
    module: str,
    amount: str,
    owner: str = "",
    age_due: str = "",
    action: str = "",
    status: str = "Open",
) -> ReportPreviewRow:
    return _cell_row(
        priority,
        alert,
        module,
        amount,
        owner,
        age_due,
        action,
        status,
    )


def _control_sort_key(row: ReportPreviewRow) -> tuple[int, int, str]:
    cells = row.cells
    priority = cells[0] if cells else ""
    module = cells[2] if len(cells) > 2 else ""
    alert = cells[1] if len(cells) > 1 else ""
    return (
        _PRIORITY_RANK.get(priority, 9),
        _MODULE_RANK.get(module, 9),
        alert.casefold(),
    )


async def _budget_overrun_rows(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
) -> list[ReportPreviewRow]:
    current = await build_department_budget_utilization_rows(
        db, tenant_id, as_of=end, current_period_only=True
    )
    window_from = start
    window_to = end
    for row in current:
        bounds = period_key_bounds(row.period_kind, row.period_key)
        if bounds is None:
            continue
        window_from = min(window_from, bounds[0])
        window_to = max(window_to, bounds[1])
    committed_rows = (
        await load_committed_claim_spend_rows(
            db, tenant_id, date_from=window_from, date_to=window_to
        )
        if current
        else []
    )
    out: list[ReportPreviewRow] = []
    for row in current:
        allocated = Decimal(str(row.allocated or 0))
        consumed = Decimal(str(row.consumed or 0))
        bounds = period_key_bounds(row.period_kind, row.period_key)
        date_from, date_to = bounds if bounds else (start, end)
        tokens = {(row.gl_ledger or "").strip().lower()}
        committed = Decimal(
            str(spend_for_tokens(committed_rows, tokens, date_from=date_from, date_to=date_to))
        )
        remaining = allocated - consumed - committed
        if remaining >= 0:
            continue
        out.append(
            _control_row(
                priority="High",
                alert=f"{row.gl_ledger} forecast above budget",
                module="Budget",
                amount=_money(abs(remaining)),
                owner=(row.department or "").strip(),
                age_due="Month end",
                action="Reforecast or reduce committed spend",
                status="Open",
            )
        )
    return out


async def _missing_receipt_rows(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    *,
    as_of: bool,
) -> list[ReportPreviewRow]:
    config = await load_posting_config_for_tenant(db, tenant_id)
    employees = await list_employee_masters(
        db, tenant_id, include_advance_balances=False
    )
    invoices = await _te_invoices_in_range(db, tenant_id, start, end, as_of=as_of)
    out: list[ReportPreviewRow] = []
    seen: set[str] = set()
    for invoice in invoices:
        employee = resolve_team_expense_employee(
            employees,
            employee_email=invoice.employee_email,
            email_sender=invoice.email_sender,
        )
        live = _missing_te_row(
            invoice,
            employee_name=employee.name if employee else "",
            employee_department=(employee.department if employee else "") or "",
            config=config,
        )
        snapshot = _failed_rules(invoice, frozenset({"VR-TE03"}))
        if live is None and not snapshot:
            continue
        ref = invoice.invoice_no or str(invoice.id or "")
        if ref in seen:
            continue
        seen.add(ref)
        out.append(
            _control_row(
                priority="Medium",
                alert=f"Expense receipt missing ({ref})" if ref else "Expense receipt missing",
                module="Expenses",
                amount=_money(Decimal(str(invoice.total or 0))),
                owner=(employee.name if employee else "") or "Employee",
                age_due=_age_due_from_date(
                    invoice.invoice_date.isoformat() if invoice.invoice_date else "",
                    end,
                ),
                action="Request receipt / declaration",
                status="Waiting",
            )
        )
    return out


async def build_control_centre(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    definition: ReportDefinition,
    start: date,
    end: date,
    *,
    as_of: bool = False,
) -> ReportPreview:
    currency = await _currency(db, tenant_id)
    schedule = await build_payment_schedule(
        db, tenant_id, CATALOG_BY_ID["payment-schedule"], end
    )
    aging, _ = await build_advance_aging(
        db, tenant_id, CATALOG_BY_ID["advance-aging"], end
    )
    policy = await build_policy_exceptions(
        db, tenant_id, CATALOG_BY_ID["policy-exceptions"], start, end
    )
    invoice_ex = await build_invoice_exception(
        db,
        tenant_id,
        CATALOG_BY_ID["invoice-exception"],
        start,
        end,
        as_of=as_of,
    )

    rows: list[ReportPreviewRow] = []
    for item in _preview_maps(schedule):
        if item.get("Timing") != "OVERDUE":
            continue
        ref = item.get("Invoice No", "")
        days = _parse_int(item.get("Days to Due", ""))
        overdue_days = abs(days) if days is not None else None
        rows.append(
            _control_row(
                priority="High",
                alert=f"Vendor invoice overdue ({ref})" if ref else "Vendor invoice overdue",
                module="Invoice-to-Pay",
                amount=item.get("Amount Due", ""),
                owner="",
                age_due=_age_due_from_days(overdue_days),
                action="Pay or schedule",
                status="Open",
            )
        )
    for item in _preview_maps(aging):
        outstanding = _parse_money(item.get("Outstanding", "") or item.get("Total", ""))
        if outstanding <= 0:
            continue
        days = _parse_int(item.get("Days Outstanding", ""))
        if days is None or days <= 60:
            continue
        ref = item.get("Advance Ref", "")
        rows.append(
            _control_row(
                priority="High",
                alert=(
                    f"Employee advance outstanding > 60 days ({ref})"
                    if ref
                    else "Employee advance outstanding > 60 days"
                ),
                module="Expenses",
                amount=item.get("Outstanding", "") or item.get("Total", ""),
                owner=item.get("Employee", ""),
                age_due=_age_due_from_days(days),
                action="Escalate to manager and employee",
                status="Open",
            )
        )
    rows.extend(await _budget_overrun_rows(db, tenant_id, start, end))
    for item in _preview_maps(policy):
        rule = item.get("Exception", "")
        ref = item.get("Claim ID", "")
        reason = item.get("Reason", "") or rule
        alert = reason
        if rule and rule not in alert:
            alert = f"{rule} · {alert}" if alert else rule
        if ref:
            alert = f"{alert} ({ref})" if alert else ref
        rows.append(
            _control_row(
                priority=item.get("Risk", "Medium") or "Medium",
                alert=alert,
                module="Expenses",
                amount=item.get("Amount", ""),
                owner=item.get("Employee", "") or item.get("Merchant", ""),
                age_due=_age_due_from_date(item.get("Date", ""), end),
                action=item.get("Recommended Action", ""),
                status="Open",
            )
        )
    for item in _preview_maps(invoice_ex):
        kind = item.get("Exception Type", "")
        ref = item.get("Invoice ID", "")
        if kind in {"Potential Duplicate", "Duplicate invoice (VR02)"}:
            alert = (
                f"Potential duplicate invoice ({ref})"
                if ref
                else "Potential duplicate invoice"
            )
            action = item.get("Action", "") or "Compare source document and hash"
            status = item.get("Status", "") or "Under review"
            priority = item.get("Risk", "High") or "High"
        else:
            alert = f"{kind} ({ref})" if ref else kind
            action = item.get("Action", "")
            status = item.get("Status", "") or "Open"
            priority = item.get("Risk", "Medium") or "Medium"
        rows.append(
            _control_row(
                priority=priority,
                alert=alert,
                module="Invoice-to-Pay",
                amount=item.get("Amount", ""),
                owner=item.get("Owner", ""),
                age_due=_age_due_from_date(item.get("Detected On", ""), end),
                action=action,
                status=status,
            )
        )
    rows.extend(
        await _missing_receipt_rows(db, tenant_id, start, end, as_of=as_of)
    )
    rows.sort(key=_control_sort_key)
    return _preview(
        definition,
        period_label=f"As of {end.isoformat()}" if as_of else _period_label(start, end),
        currency=currency,
        columns=list(_CONTROL_COLUMNS),
        rows=rows,
        notes=_CONTROL_CENTRE_NOTES,
    )
