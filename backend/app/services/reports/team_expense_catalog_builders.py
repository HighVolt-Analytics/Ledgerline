"""Team Expense catalog builders (invoices + Staff Advance journals + employee_masters)."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict, deque
from datetime import date
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry
from app.models.tenant import Tenant
from app.schemas.report_catalog import ReportPreview, ReportPreviewRow
from app.schemas.rule_book_config import (
    TEAM_EXPENSE_KIND_ADVANCE,
    TEAM_EXPENSE_KIND_CLAIM,
    TEAM_EXPENSE_KIND_DIRECT,
    normalize_team_expense_kind,
)
from app.services.invoice.invoice_evaluation_service import (
    EVAL_PENDING_APPROVAL,
    ROUTE_SALES,
    ROUTE_TEAM,
    ROUTE_VAULT,
    load_posting_config_for_tenant,
)
from app.services.master_data.master_data_service import list_employee_masters
from app.services.purchase.team_expense_advance_service import (
    employee_advance_account_code,
    employee_advance_activity_by_ids,
)
from app.services.purchase.team_expense_validator import (
    has_receipt_attachment,
    resolve_team_expense_employee,
    vr_te03_receipt,
)
from app.services.reports.payables_catalog_builders import last_approval
from app.services.reports.report_catalog import ReportDefinition
from app.services.reports.team_expense_reports_service import build_advance_settlement_rows
from app.services.rule_book.rule_book_evaluate_service import invoice_to_eval_document
from app.services.rule_book.rule_engine import match_team_expense_rule
from app.tenant_settings import tenant_currency

_ZERO = Decimal("0.00")
_AGE_BUCKETS = ("0–30", "31–60", "61–90", "90+")
_ADVANCE_AGING_COLUMNS = [
    "Employee",
    "Advance Ref",
    "Date Issued",
    "Advance Issued",
    "Amount Settled",
    "Outstanding",
    "Days Outstanding",
    *_AGE_BUCKETS,
]
_ADVANCE_AGING_NOTES = (
    "Unsettled advances bucketed by age from date issued. Chase the 60+ columns at close."
)
_CLAIM_KINDS = frozenset({TEAM_EXPENSE_KIND_CLAIM, "expense_against_advance"})
_POLICY_RULES = frozenset(
    {"VR-TE04", "VR-TE05", "VR-TE08", "VR-TE09", "VR-TE10", "VR-TE11"}
)
_CLAIM_REGISTER_COLUMNS = [
    "Claim ID",
    "Employee",
    "Date",
    "Dept / Project",
    "Category",
    "Amount",
    "Against Advance?",
    "Receipt Attached?",
    "Within Policy",
    "Status",
    "Approver",
]
_CLAIM_REGISTER_NOTES = (
    "Every claim line. Feeds Advance Reconciliation and Reimbursement Due. "
    "Receipt & policy flags support File Management."
)
_POSTED_EXCLUDED = (
    InvoiceStatus.PROCESSED,
    InvoiceStatus.REJECTED,
    InvoiceStatus.DUPLICATE_SKIPPED,
)
_REIMBURSEMENT_COLUMNS = [
    "Employee",
    "From Advances (Co. owes)",
    "Out-of-pocket Claims",
    "Total Due",
    "Payment Status",
]
_REIMBURSEMENT_NOTES = (
    "Green cells pull from Advance Reconciliation (Co. owes) and Expense Claims "
    "(out-of-pocket, not against advance)."
)
_MISSING_SKIP_ROUTES = frozenset({ROUTE_SALES, ROUTE_VAULT})
_MISSING_DOC_COLUMNS = [
    "Type",
    "Reference ID",
    "Owner",
    "Expected Document",
    "Attached",
    "Flag",
    "Notes",
]
_MISSING_DOC_NOTES = (
    "Anything expected-but-not-attached. This is the report that makes the other tabs audit-ready."
)


def _money(value: Decimal | None) -> str:
    return f"{(value or _ZERO).quantize(Decimal('0.01')):,.2f}"


def _summary_money(value: Decimal) -> str:
    if value == 0:
        return "-"
    return _money(value)


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


def _age_bucket(journal_date: date, as_of: date) -> str:
    days = (as_of - journal_date).days
    if days <= 30:
        return "0–30"
    if days <= 60:
        return "31–60"
    if days <= 90:
        return "61–90"
    return "90+"


def _days_outstanding_bucket(days: int) -> str:
    if days <= 30:
        return "0–30"
    if days <= 60:
        return "31–60"
    if days <= 90:
        return "61–90"
    return "90+"


def fifo_age_outstanding(
    movements: Sequence[tuple[date, Decimal, Decimal]],
    as_of: date,
) -> dict[str, Decimal] | None:
    """Age leftover Staff Advance debit lots. None when outstanding <= 0 (including over-claim)."""
    lots: deque[list] = deque()
    for day, debit, credit in movements:
        debit_amt = Decimal(str(debit or 0))
        credit_amt = Decimal(str(credit or 0))
        if debit_amt > 0:
            lots.append([day, debit_amt])
        remaining_credit = credit_amt
        while remaining_credit > 0 and lots:
            lot_date, lot_amt = lots[0]
            take = min(lot_amt, remaining_credit)
            lot_amt -= take
            remaining_credit -= take
            if lot_amt <= 0:
                lots.popleft()
            else:
                lots[0][1] = lot_amt
    buckets = {name: _ZERO for name in _AGE_BUCKETS}
    outstanding = _ZERO
    for lot_date, lot_amt in lots:
        if lot_amt <= 0:
            continue
        outstanding += lot_amt
        buckets[_age_bucket(lot_date, as_of)] += lot_amt
    if outstanding <= 0:
        return None
    buckets["Total"] = outstanding
    return buckets


def fifo_remaining_by_invoice(
    movements: Sequence[tuple[date, Decimal, Decimal, int | None]],
) -> tuple[dict[int | None, Decimal], dict[int | None, Decimal], dict[int | None, date]]:
    """FIFO leftover and issued totals keyed by invoice_id."""
    lots: deque[list] = deque()
    issued: dict[int | None, Decimal] = defaultdict(lambda: _ZERO)
    first_debit: dict[int | None, date] = {}
    for day, debit, credit, invoice_id in movements:
        debit_amt = Decimal(str(debit or 0))
        credit_amt = Decimal(str(credit or 0))
        if debit_amt > 0:
            lots.append([day, debit_amt, invoice_id])
            issued[invoice_id] += debit_amt
            first_debit.setdefault(invoice_id, day)
        remaining_credit = credit_amt
        while remaining_credit > 0 and lots:
            _lot_date, lot_amt, lot_invoice = lots[0]
            take = min(lot_amt, remaining_credit)
            lot_amt -= take
            remaining_credit -= take
            if lot_amt <= 0:
                lots.popleft()
            else:
                lots[0][1] = lot_amt
    leftover: dict[int | None, Decimal] = defaultdict(lambda: _ZERO)
    for _lot_date, lot_amt, lot_invoice in lots:
        leftover[lot_invoice] += lot_amt
    return leftover, dict(issued), first_debit


async def build_advance_reconciliation(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    definition: ReportDefinition,
    start: date,
    end: date,
) -> ReportPreview:
    currency = await _currency(db, tenant_id)
    settlement = await build_advance_settlement_rows(db, tenant_id)
    rows: list[ReportPreviewRow] = []
    for row in settlement:
        outstanding = Decimal(str(row.advance_ledger_balance or 0))
        taken = Decimal(str(row.advance_taken or 0))
        used = Decimal(str(row.advance_used or 0))
        pending = Decimal(str(row.pending_against_advance or 0))
        available = Decimal(str(row.available_advance or 0))
        if taken == 0 and used == 0 and outstanding == 0 and pending == 0:
            continue
        rows.append(
            _cell_row(
                row.name or row.employee_id,
                row.email or "",
                _money(taken),
                _money(used),
                _money(outstanding),
                _money(pending),
                _money(available),
            )
        )
    return _preview(
        definition,
        period_label=_period_label(start, end),
        currency=currency,
        columns=["Employee", "Email", "Taken", "Used", "Outstanding", "Pending claims", "Available"],
        rows=rows,
    )


async def build_advance_aging(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    definition: ReportDefinition,
    as_of: date,
) -> tuple[ReportPreview, list[list[Any]]]:
    currency = await _currency(db, tenant_id)
    config = await load_posting_config_for_tenant(db, tenant_id)
    employees = await list_employee_masters(
        db, tenant_id, include_advance_balances=False
    )
    activity = await employee_advance_activity_by_ids(
        db, tenant_id, config, employees
    )
    code_to_emp: dict[str, Any] = {}
    for emp in employees:
        emp_id = (emp.id or "").strip()
        if not emp_id:
            continue
        taken, used, outstanding = activity.get(
            emp_id, (_ZERO, _ZERO, _ZERO)
        )
        if used > taken:
            continue
        if taken <= 0 and outstanding <= 0:
            continue
        code = employee_advance_account_code(
            config,
            employee_id=emp_id,
            employee_parent_ledger=emp.advance_parent_ledger or "",
        )
        if code:
            code_to_emp[code] = emp

    excel_rows: list[list[Any]] = []
    preview_rows: list[ReportPreviewRow] = []

    def _empty() -> tuple[ReportPreview, list[list[Any]]]:
        return (
            _preview(
                definition,
                period_label=f"As of {as_of.isoformat()}",
                currency=currency,
                columns=list(_ADVANCE_AGING_COLUMNS),
                rows=[],
                notes=_ADVANCE_AGING_NOTES,
            ),
            excel_rows,
        )

    if not code_to_emp:
        return _empty()

    journals = (
        await db.execute(
            select(JournalEntry)
            .where(
                JournalEntry.tenant_id == tenant_id,
                JournalEntry.account_code.in_(list(code_to_emp.keys())),
                JournalEntry.date <= as_of,
            )
            .order_by(JournalEntry.date.asc(), JournalEntry.id.asc())
        )
    ).scalars().all()
    by_code: dict[str, list[tuple[date, Decimal, Decimal, int | None]]] = defaultdict(list)
    for entry in journals:
        by_code[entry.account_code].append(
            (
                entry.date,
                Decimal(str(entry.debit or 0)),
                Decimal(str(entry.credit or 0)),
                entry.invoice_id,
            )
        )

    invoice_ids = {
        invoice_id
        for movements in by_code.values()
        for _day, debit, _credit, invoice_id in movements
        if invoice_id is not None and debit > 0
    }
    invoices: dict[int, Invoice] = {}
    if invoice_ids:
        loaded = (
            await db.execute(
                select(Invoice).where(
                    Invoice.tenant_id == tenant_id,
                    Invoice.id.in_(list(invoice_ids)),
                )
            )
        ).scalars().all()
        invoices = {row.id: row for row in loaded if row.id is not None}

    line_items: list[tuple[str, str, date | None, Decimal, Decimal, Decimal, int | None]] = []
    for code, emp in code_to_emp.items():
        leftover, issued, first_debit = fifo_remaining_by_invoice(by_code.get(code, []))
        for invoice_id, issued_amt in issued.items():
            if issued_amt <= 0:
                continue
            invoice = invoices.get(invoice_id) if invoice_id is not None else None
            remaining = leftover.get(invoice_id, _ZERO)
            settled = issued_amt - remaining
            if settled < 0:
                settled = _ZERO
            issued_on = None
            if invoice is not None and invoice.invoice_date is not None:
                issued_on = invoice.invoice_date
            elif invoice_id in first_debit:
                issued_on = first_debit[invoice_id]
            days = (as_of - issued_on).days if issued_on is not None else None
            line_items.append(
                (
                    emp.name or emp.id or "",
                    (invoice.invoice_no if invoice is not None else "") or "",
                    issued_on,
                    issued_amt,
                    settled,
                    remaining,
                    days,
                )
            )

    line_items.sort(key=lambda item: (item[0].casefold(), item[2] or date.min, item[1]))
    grand_issued = _ZERO
    grand_settled = _ZERO
    grand_outstanding = _ZERO
    grand_buckets = {name: _ZERO for name in _AGE_BUCKETS}
    for employee, ref, issued_on, issued_amt, settled, remaining, days in line_items:
        buckets = {name: _ZERO for name in _AGE_BUCKETS}
        if remaining > 0 and days is not None:
            buckets[_days_outstanding_bucket(days)] = remaining
        preview_rows.append(
            _cell_row(
                employee,
                ref,
                issued_on.isoformat() if issued_on else "",
                _money(issued_amt),
                _money(settled),
                _summary_money(remaining),
                "" if days is None else str(days),
                *(_summary_money(buckets[name]) for name in _AGE_BUCKETS),
            )
        )
        excel_rows.append(
            [
                employee,
                ref,
                issued_on.isoformat() if issued_on else "",
                float(issued_amt),
                float(settled),
                float(remaining),
                "" if days is None else days,
                *(float(buckets[name]) for name in _AGE_BUCKETS),
            ]
        )
        grand_issued += issued_amt
        grand_settled += settled
        grand_outstanding += remaining
        for name in _AGE_BUCKETS:
            grand_buckets[name] += buckets[name]

    if preview_rows:
        preview_rows.append(
            _cell_row(
                "TOTAL",
                "",
                "",
                _money(grand_issued),
                _money(grand_settled),
                _summary_money(grand_outstanding),
                "",
                *(_summary_money(grand_buckets[name]) for name in _AGE_BUCKETS),
                emphasize=True,
            )
        )
    preview = _preview(
        definition,
        period_label=f"As of {as_of.isoformat()}",
        currency=currency,
        columns=list(_ADVANCE_AGING_COLUMNS),
        rows=preview_rows,
        notes=_ADVANCE_AGING_NOTES,
    )
    return preview, excel_rows


def _yes_no(value: bool) -> str:
    return "Yes" if value else "No"


def _against_advance(invoice: Invoice) -> bool:
    raw = (invoice.team_expense_kind or "").strip().lower()
    return raw == "expense_against_advance"


def _within_policy(invoice: Invoice) -> bool:
    raw = invoice.validation_results
    if not raw:
        return True
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        return True
    if not isinstance(payload, list):
        return True
    for row in payload:
        if not isinstance(row, dict):
            continue
        rule = str(row.get("rule") or "").strip()
        if rule not in _POLICY_RULES:
            continue
        if row.get("skipped") or row.get("passed"):
            continue
        return False
    return True


def _claim_status(invoice: Invoice) -> str:
    eval_status = (invoice.evaluation_status or "").strip().lower()
    if eval_status == EVAL_PENDING_APPROVAL:
        return "Pending approval"
    name, _ = last_approval(invoice.approval_chain)
    if name:
        return "Approved"
    if invoice.status == InvoiceStatus.PROCESSED:
        return "Approved"
    if invoice.status == InvoiceStatus.REJECTED:
        return "Rejected"
    return _text(getattr(invoice.status, "value", invoice.status))


def _claim_register_row(invoice: Invoice, employee_name: str, department: str) -> list[str]:
    approver, _approved_on = last_approval(invoice.approval_chain)
    return [
        invoice.invoice_no or "",
        employee_name,
        invoice.invoice_date.isoformat() if invoice.invoice_date else "",
        department or (invoice.cost_centre or ""),
        invoice.account_name or invoice.account_code or "",
        _money(Decimal(str(invoice.total or 0))),
        _yes_no(_against_advance(invoice)),
        _yes_no(has_receipt_attachment(invoice.raw_file_path)),
        _yes_no(_within_policy(invoice)),
        _claim_status(invoice),
        approver,
    ]


async def _invoices_in_range(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    *,
    as_of: bool = False,
    team_only: bool = True,
) -> list[Invoice]:
    if as_of:
        date_clause = or_(Invoice.invoice_date.is_(None), Invoice.invoice_date <= end)
        order = (Invoice.invoice_date, Invoice.id)
    else:
        date_clause = (
            Invoice.invoice_date.is_not(None)
            & (Invoice.invoice_date >= start)
            & (Invoice.invoice_date <= end)
        )
        order = (Invoice.invoice_date, Invoice.id)
    filters = [
        Invoice.tenant_id == tenant_id,
        date_clause,
    ]
    if team_only:
        filters.append(Invoice.route_target == ROUTE_TEAM)
    stmt = select(Invoice).where(*filters).order_by(*order)
    return list((await db.execute(stmt)).scalars().all())


async def _te_invoices_in_range(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    *,
    as_of: bool = False,
) -> list[Invoice]:
    return await _invoices_in_range(db, tenant_id, start, end, as_of=as_of, team_only=True)


async def build_expense_claims_register(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    definition: ReportDefinition,
    start: date,
    end: date,
    *,
    as_of: bool = False,
) -> tuple[ReportPreview, list[list[Any]]]:
    currency = await _currency(db, tenant_id)
    employees = await list_employee_masters(
        db, tenant_id, include_advance_balances=False
    )
    invoices = await _te_invoices_in_range(db, tenant_id, start, end, as_of=as_of)
    preview_rows: list[ReportPreviewRow] = []
    excel_rows: list[list[Any]] = []
    for invoice in invoices:
        kind = normalize_team_expense_kind(invoice.team_expense_kind)
        if kind == TEAM_EXPENSE_KIND_ADVANCE or kind == TEAM_EXPENSE_KIND_DIRECT:
            continue
        if kind and kind not in _CLAIM_KINDS and kind != TEAM_EXPENSE_KIND_CLAIM:
            continue
        employee = resolve_team_expense_employee(
            employees,
            employee_email=invoice.employee_email,
            email_sender=invoice.email_sender,
        )
        cells = _claim_register_row(
            invoice,
            employee.name if employee else "",
            (employee.department if employee else "") or "",
        )
        preview_rows.append(_cell_row(*cells))
        excel_rows.append(cells)
    preview = _preview(
        definition,
        period_label=f"As of {end.isoformat()}" if as_of else _period_label(start, end),
        currency=currency,
        columns=list(_CLAIM_REGISTER_COLUMNS),
        rows=preview_rows,
        notes=_CLAIM_REGISTER_NOTES,
    )
    return preview, excel_rows


def _open_for_reimbursement(invoice: Invoice) -> bool:
    if invoice.status in _POSTED_EXCLUDED:
        return False
    eval_status = (invoice.evaluation_status or "").strip().lower()
    if eval_status == EVAL_PENDING_APPROVAL:
        return False
    kind = normalize_team_expense_kind(invoice.team_expense_kind)
    if kind == TEAM_EXPENSE_KIND_ADVANCE or kind == TEAM_EXPENSE_KIND_DIRECT:
        return False
    return True


async def build_reimbursement_due(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    definition: ReportDefinition,
    start: date,
    end: date,
    *,
    as_of: bool = False,
) -> tuple[ReportPreview, list[list[Any]]]:
    currency = await _currency(db, tenant_id)
    config = await load_posting_config_for_tenant(db, tenant_id)
    employees = await list_employee_masters(
        db, tenant_id, include_advance_balances=False
    )
    activity = await employee_advance_activity_by_ids(
        db, tenant_id, config, employees
    )
    invoices = await _te_invoices_in_range(db, tenant_id, start, end, as_of=as_of)
    against_by_emp: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    pocket_by_emp: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    for invoice in invoices:
        if not _open_for_reimbursement(invoice):
            continue
        employee = resolve_team_expense_employee(
            employees,
            employee_email=invoice.employee_email,
            email_sender=invoice.email_sender,
        )
        if employee is None or not (employee.id or "").strip():
            continue
        amount = Decimal(str(invoice.total or 0))
        if _against_advance(invoice):
            against_by_emp[employee.id] += amount
        else:
            pocket_by_emp[employee.id] += amount

    line_items: list[tuple[str, Decimal, Decimal, Decimal]] = []
    for emp in employees:
        emp_id = (emp.id or "").strip()
        if not emp_id:
            continue
        _taken, _used, outstanding = activity.get(emp_id, (_ZERO, _ZERO, _ZERO))
        from_adv = against_by_emp.get(emp_id, _ZERO) - outstanding
        if from_adv < 0:
            from_adv = _ZERO
        pocket = pocket_by_emp.get(emp_id, _ZERO)
        if from_adv == 0 and pocket == 0:
            continue
        total = from_adv + pocket
        line_items.append((emp.name or emp_id, from_adv, pocket, total))
    line_items.sort(key=lambda item: item[0].casefold())

    preview_rows: list[ReportPreviewRow] = []
    excel_rows: list[list[Any]] = []
    grand_adv = _ZERO
    grand_pocket = _ZERO
    grand_total = _ZERO
    for name, from_adv, pocket, total in line_items:
        cells = [
            name,
            _summary_money(from_adv),
            _summary_money(pocket),
            _summary_money(total),
            "",
        ]
        preview_rows.append(_cell_row(*cells))
        excel_rows.append(cells)
        grand_adv += from_adv
        grand_pocket += pocket
        grand_total += total
    if preview_rows:
        total_cells = [
            "TOTAL",
            _summary_money(grand_adv),
            _summary_money(grand_pocket),
            _summary_money(grand_total),
            "",
        ]
        preview_rows.append(_cell_row(*total_cells, emphasize=True))
        excel_rows.append(total_cells)
    preview = _preview(
        definition,
        period_label=f"As of {end.isoformat()}" if as_of else _period_label(start, end),
        currency=currency,
        columns=list(_REIMBURSEMENT_COLUMNS),
        rows=preview_rows,
        notes=_REIMBURSEMENT_NOTES,
    )
    return preview, excel_rows


def _missing_te_row(
    invoice: Invoice,
    *,
    employee_name: str,
    employee_department: str,
    config: Any,
) -> list[str] | None:
    has_file = has_receipt_attachment(invoice.raw_file_path)
    team_rule = None
    try:
        doc = invoice_to_eval_document(invoice)
        team_rule = match_team_expense_rule(
            doc,
            config.team_expense_rules,
            amount=float(invoice.total) if invoice.total is not None else None,
            employee_department=employee_department or None,
        )
    except Exception:
        team_rule = None
    te03 = vr_te03_receipt(
        team_rule,
        float(invoice.total) if invoice.total is not None else None,
        has_receipt_file=has_file,
        team_expense_kind=invoice.team_expense_kind,
    )
    if te03.passed:
        return None
    notes: list[str] = []
    if not has_file:
        notes.append("No stored file")
    notes.append(f"VR-TE03: {te03.message}")
    return [
        "Expense claim",
        invoice.invoice_no or "",
        employee_name or (invoice.vendor or ""),
        "Receipt",
        "N",
        "MISSING",
        "; ".join(notes),
    ]


def _missing_ap_row(invoice: Invoice) -> list[str] | None:
    if (invoice.raw_file_path or "").strip():
        return None
    return [
        "Invoice",
        invoice.invoice_no or "",
        invoice.vendor or "",
        "Tax invoice PDF",
        "N",
        "MISSING",
        "Vendor to resend",
    ]


async def build_missing_documents(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    definition: ReportDefinition,
    start: date,
    end: date,
    *,
    as_of: bool = False,
) -> tuple[ReportPreview, list[list[Any]]]:
    currency = await _currency(db, tenant_id)
    config = await load_posting_config_for_tenant(db, tenant_id)
    employees = await list_employee_masters(
        db, tenant_id, include_advance_balances=False
    )
    invoices = await _invoices_in_range(
        db, tenant_id, start, end, as_of=as_of, team_only=False
    )
    preview_rows: list[ReportPreviewRow] = []
    excel_rows: list[list[Any]] = []
    for invoice in invoices:
        route = (invoice.route_target or "").strip()
        if route in _MISSING_SKIP_ROUTES:
            continue
        if route == ROUTE_TEAM:
            employee = resolve_team_expense_employee(
                employees,
                employee_email=invoice.employee_email,
                email_sender=invoice.email_sender,
            )
            cells = _missing_te_row(
                invoice,
                employee_name=employee.name if employee else "",
                employee_department=(employee.department if employee else "") or "",
                config=config,
            )
        else:
            cells = _missing_ap_row(invoice)
        if not cells:
            continue
        preview_rows.append(_cell_row(*cells))
        excel_rows.append(cells)
    preview = _preview(
        definition,
        period_label=f"As of {end.isoformat()}" if as_of else _period_label(start, end),
        currency=currency,
        columns=list(_MISSING_DOC_COLUMNS),
        rows=preview_rows,
        notes=_MISSING_DOC_NOTES,
    )
    return preview, excel_rows


async def settlement_excel_rows(
    db: AsyncSession, tenant_id: uuid.UUID
) -> list[list[Any]]:
    rows = await build_advance_settlement_rows(db, tenant_id)
    out: list[list[Any]] = []
    for row in rows:
        taken = Decimal(str(row.advance_taken or 0))
        used = Decimal(str(row.advance_used or 0))
        outstanding = Decimal(str(row.advance_ledger_balance or 0))
        pending = Decimal(str(row.pending_against_advance or 0))
        if taken == 0 and used == 0 and outstanding == 0 and pending == 0:
            continue
        out.append(
            [
                row.employee_id,
                row.name,
                row.email,
                float(taken),
                float(used),
                float(outstanding),
                float(pending),
                float(Decimal(str(row.available_advance or 0))),
            ]
        )
    return out
