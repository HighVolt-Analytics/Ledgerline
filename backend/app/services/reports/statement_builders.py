"""Build live report preview tables from invoices, budgets, and team expenses.

Every select filters Model.tenant_id == tenant_id on each table it reads —
same pattern as subledger_balance_service and department budget utilization.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.schemas.report_catalog import ReportPreview, ReportPreviewRow, ReportRange
from app.services.master_data.department_budget_service import (
    build_department_budget_utilization_rows,
)
from app.services.purchase.team_expense_spend_service import (
    current_period_keys,
    load_committed_claim_spend_rows,
    period_key_bounds,
    spend_for_tokens,
)
from app.services.reports.dashboard_service import _institution_today
from app.services.reports.exception_status_catalog_builders import (
    build_claim_status,
    build_control_centre,
    build_invoice_exception,
    build_policy_exceptions,
    build_process_efficiency,
)
from app.services.reports.payables_catalog_builders import (
    ap_outstanding_rows,
    build_cash_forecast,
    build_invoice_register,
    build_payment_schedule,
    build_vendor_spend_summary,
)
from app.services.reports.report_catalog import ReportDefinition, get_report_or_raise
from app.services.reports.team_expense_catalog_builders import (
    build_advance_aging,
    build_advance_reconciliation,
    build_expense_claims_register,
    build_missing_documents,
    build_reimbursement_due,
)
from app.tenant_settings import tenant_currency

_ZERO = Decimal("0.00")
_BUDGET_VARIANCE_NOTES = (
    "Variance and utilisation by department / project / category. "
    "Committed = approved-but-not-yet-spent (in-flight Team Expense claims only; "
    "open POs and unposted vendor invoices are not encumbered)."
)


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):,.2f}"


def _cell_row(*cells: str, emphasize: bool = False) -> ReportPreviewRow:
    return ReportPreviewRow(cells=list(cells), emphasize=emphasize)


def _prior_window(start: date, end: date) -> tuple[date, date]:
    length = (end - start).days + 1
    prior_end = start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=length - 1)
    return prior_start, prior_end


def _period_label(start: date, end: date) -> str:
    if start == end:
        return start.isoformat()
    return f"{start.isoformat()} – {end.isoformat()}"


async def resolve_report_window(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    range_key: ReportRange,
    date_from: date | None,
    date_to: date | None,
) -> tuple[date, date]:
    today = await _institution_today(db, tenant_id)
    if range_key == "month":
        start = date(today.year, today.month, 1)
        end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
        return start, end
    if range_key == "quarter":
        q = (today.month - 1) // 3
        start_month = q * 3 + 1
        start = date(today.year, start_month, 1)
        end_month = start_month + 2
        end = date(today.year, end_month, calendar.monthrange(today.year, end_month)[1])
        return start, end
    if date_from is None or date_to is None:
        raise ValueError("from and to are required for a custom range")
    if date_from > date_to:
        raise ValueError("from must be on or before to")
    return date_from, date_to


async def _tenant_currency(db: AsyncSession, tenant_id: uuid.UUID) -> str:
    tenant = await db.get(Tenant, tenant_id)
    return tenant_currency(tenant)


def _preview(
    definition: ReportDefinition,
    *,
    period_label: str,
    currency: str,
    columns: list[str],
    rows: list[ReportPreviewRow],
    compare_columns: list[str] | None = None,
    notes: str | None = None,
) -> ReportPreview:
    return ReportPreview(
        report_id=definition.id,
        title=definition.name,
        period_label=period_label,
        currency=currency,
        columns=columns,
        rows=rows,
        compare_columns=compare_columns,
        empty=len(rows) == 0,
        notes=notes,
    )


def _age_bucket(due: date | None, as_of: date) -> str:
    if due is None:
        return "Current"
    days = (as_of - due).days
    if days <= 0:
        return "Current"
    if days <= 30:
        return "1–30"
    if days <= 60:
        return "31–60"
    if days <= 90:
        return "61–90"
    return "90+"


def _days_overdue(due: date | None, as_of: date) -> int:
    if due is None:
        return 0
    return max(0, (as_of - due).days)


def _pct_of(part: Decimal, whole: Decimal) -> str:
    if whole == 0:
        return "-"
    q = (part / whole * Decimal("100")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{q}%"


def _budget_bounds_in_window(
    period_kind: str,
    period_key: str,
    start: date,
    end: date,
    *,
    as_of: bool,
) -> bool:
    bounds = period_key_bounds(period_kind, period_key)
    if bounds is None:
        return False
    period_from, period_to = bounds
    if as_of:
        return period_from <= end
    return period_from <= end and period_to >= start


def _budget_category_label(gl_ledger: str, period_kind: str, period_key: str, as_of: date) -> str:
    name = (gl_ledger or "").strip()
    current = current_period_keys(as_of).get((period_kind or "").strip().lower())
    if current and current == (period_key or "").strip():
        return name
    extra = (period_key or "").strip()
    if extra:
        return f"{name} · {extra}" if name else extra
    return name


def _bucket_cell(amount: Decimal) -> str:
    if amount == 0:
        return "-"
    return _money(amount)


async def _build_aged(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    definition: ReportDefinition,
    as_of: date,
) -> ReportPreview:
    currency = await _tenant_currency(db, tenant_id)
    buckets = ("Current", "1–30", "31–60", "61–90", "90+")
    columns = [
        "Vendor",
        "Invoice No",
        "Invoice Date",
        "Due Date",
        "Invoice Amount",
        "Amount Paid",
        "Balance Due",
        "Days Overdue",
        *buckets,
    ]
    table_rows: list[ReportPreviewRow] = []
    grand_invoiced = _ZERO
    grand_paid = _ZERO
    grand_balance = _ZERO
    grand = {bucket: _ZERO for bucket in buckets}
    line_items: list[tuple[str, str, str, str, Decimal, Decimal, Decimal, int, str]] = []
    for row in await ap_outstanding_rows(db, tenant_id, as_of):
        party = (row.vendor or "Unregistered").strip() or "Unregistered"
        invoice_no = (row.invoice_no or row.document_ref or "").strip()
        invoiced = row.invoice_total
        remaining = row.remaining
        paid = invoiced - remaining
        days = _days_overdue(row.due_date, as_of)
        bucket = _age_bucket(row.due_date, as_of)
        line_items.append(
            (
                party,
                invoice_no,
                row.invoice_date.isoformat() if row.invoice_date else "",
                row.due_date.isoformat() if row.due_date else "",
                invoiced,
                paid,
                remaining,
                days,
                bucket,
            )
        )
    for (
        party,
        invoice_no,
        invoice_date,
        due_date,
        invoiced,
        paid,
        remaining,
        days,
        bucket,
    ) in sorted(line_items, key=lambda item: (item[0], item[1])):
        amounts = {name: _ZERO for name in buckets}
        amounts[bucket] = remaining
        table_rows.append(
            _cell_row(
                party,
                invoice_no,
                invoice_date,
                due_date,
                _money(invoiced),
                _money(paid),
                _money(remaining),
                str(days),
                *(_bucket_cell(amounts[b]) for b in buckets),
            )
        )
        grand_invoiced += invoiced
        grand_paid += paid
        grand_balance += remaining
        grand[bucket] += remaining

    if table_rows:
        table_rows.append(
            _cell_row(
                "Total",
                "",
                "",
                "",
                _money(grand_invoiced),
                _money(grand_paid),
                _money(grand_balance),
                "",
                *(_bucket_cell(grand[b]) for b in buckets),
                emphasize=True,
            )
        )
    return _preview(
        definition,
        period_label=f"As of {as_of.isoformat()}",
        currency=currency,
        columns=columns,
        rows=table_rows,
    )


async def _build_budget_variance(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    definition: ReportDefinition,
    start: date,
    end: date,
    compare: bool,
    *,
    as_of: bool = False,
) -> ReportPreview:
    currency = await _tenant_currency(db, tenant_id)
    loaded = await build_department_budget_utilization_rows(
        db, tenant_id, as_of=end, current_period_only=False
    )
    current = [
        row
        for row in loaded
        if _budget_bounds_in_window(
            row.period_kind, row.period_key, start, end, as_of=as_of
        )
    ]
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

    def _committed_for(row) -> Decimal:
        bounds = period_key_bounds(row.period_kind, row.period_key)
        date_from, date_to = bounds if bounds else (start, end)
        tokens = { (row.gl_ledger or "").strip().lower() }
        return Decimal(
            str(
                spend_for_tokens(
                    committed_rows, tokens, date_from=date_from, date_to=date_to
                )
            )
        )

    prior_map: dict[str, Decimal] = {}
    if compare:
        prior_start, prior_end = _prior_window(start, end)
        prior_rows = await build_department_budget_utilization_rows(
            db, tenant_id, as_of=prior_end, current_period_only=True
        )
        prior_map = {
            row.gl_ledger: Decimal(str(row.allocated or 0)) - Decimal(str(row.consumed or 0))
            for row in prior_rows
        }

    columns = [
        "Department / Project",
        "Category",
        "Budget",
        "Committed",
        "Actual",
        "Variance",
        "Variance %",
        "% Utilise",
    ]
    if compare:
        columns = [*columns, "Prior variance"]

    rows: list[ReportPreviewRow] = []
    grand_budget = _ZERO
    grand_committed = _ZERO
    grand_actual = _ZERO
    grand_prior = _ZERO
    ordered = sorted(
        current,
        key=lambda row: (
            (row.department or "").casefold(),
            (row.gl_ledger or "").casefold(),
        ),
    )
    for row in ordered:
        allocated = Decimal(str(row.allocated or 0))
        consumed = Decimal(str(row.consumed or 0))
        committed = _committed_for(row)
        variance = allocated - consumed
        utilised = consumed + committed
        cells = [
            (row.department or "").strip(),
            _budget_category_label(row.gl_ledger, row.period_kind, row.period_key, end),
            _money(allocated),
            _money(committed),
            _money(consumed),
            _money(variance),
            _pct_of(variance, allocated),
            _pct_of(utilised, allocated),
        ]
        if compare:
            prior = prior_map.get(row.gl_ledger, _ZERO)
            cells.append(_money(prior))
            grand_prior += prior
        rows.append(_cell_row(*cells))
        grand_budget += allocated
        grand_committed += committed
        grand_actual += consumed

    if rows:
        total_variance = grand_budget - grand_actual
        total_cells = [
            "TOTAL",
            "",
            _money(grand_budget),
            _money(grand_committed),
            _money(grand_actual),
            _money(total_variance),
            _pct_of(total_variance, grand_budget),
            _pct_of(grand_committed + grand_actual, grand_budget),
        ]
        if compare:
            total_cells.append(_money(grand_prior))
        rows.append(_cell_row(*total_cells, emphasize=True))

    return _preview(
        definition,
        period_label=_period_label(start, end),
        currency=currency,
        columns=columns,
        rows=rows,
        compare_columns=["Variance", "Prior variance"] if compare else None,
        notes=_BUDGET_VARIANCE_NOTES
        if rows
        else (
            f"{_BUDGET_VARIANCE_NOTES} No GL account budget is set on or before this as-at date. "
            "Add a budget on Settings → GL Budget."
        ),
    )


async def build_report_preview(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    report_id: str,
    *,
    range_key: ReportRange = "month",
    compare: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
) -> ReportPreview:
    definition = get_report_or_raise(report_id)
    start, end = await resolve_report_window(db, tenant_id, range_key, date_from, date_to)
    use_compare = compare and definition.supports_compare

    if report_id == "aged-payables":
        return await _build_aged(db, tenant_id, definition, end)
    if report_id == "payment-schedule":
        return await build_payment_schedule(db, tenant_id, definition, end)
    if report_id == "invoice-register":
        return await build_invoice_register(
            db,
            tenant_id,
            definition,
            start,
            end,
            as_of=range_key != "custom",
        )
    if report_id == "vendor-spend-summary":
        return await build_vendor_spend_summary(
            db,
            tenant_id,
            definition,
            start,
            end,
            as_of=range_key != "custom",
        )
    if report_id == "cash-forecast":
        return await build_cash_forecast(db, tenant_id, definition, end)
    if report_id == "budget-variance":
        return await _build_budget_variance(
            db,
            tenant_id,
            definition,
            start,
            end,
            use_compare,
            as_of=range_key != "custom",
        )
    if report_id == "advance-reconciliation":
        return await build_advance_reconciliation(
            db, tenant_id, definition, start, end
        )
    if report_id == "advance-aging":
        preview, _ = await build_advance_aging(db, tenant_id, definition, end)
        return preview
    if report_id == "expense-claims-register":
        preview, _ = await build_expense_claims_register(
            db, tenant_id, definition, start, end, as_of=range_key != "custom"
        )
        return preview
    if report_id == "reimbursement-due":
        preview, _ = await build_reimbursement_due(
            db, tenant_id, definition, start, end, as_of=range_key != "custom"
        )
        return preview
    if report_id == "missing-documents":
        preview, _ = await build_missing_documents(
            db, tenant_id, definition, start, end, as_of=range_key != "custom"
        )
        return preview
    if report_id == "claim-status":
        return await build_claim_status(
            db, tenant_id, definition, start, end, as_of=range_key != "custom"
        )
    if report_id == "policy-exceptions":
        return await build_policy_exceptions(db, tenant_id, definition, start, end)
    if report_id == "invoice-exception":
        return await build_invoice_exception(
            db, tenant_id, definition, start, end, as_of=range_key != "custom"
        )
    if report_id == "process-efficiency":
        prior_start, prior_end = _prior_window(start, end)
        return await build_process_efficiency(
            db,
            tenant_id,
            definition,
            start,
            end,
            prior_start=prior_start,
            prior_end=prior_end,
        )
    if report_id == "control-centre":
        return await build_control_centre(
            db, tenant_id, definition, start, end, as_of=range_key != "custom"
        )
    raise LookupError(f"Unknown report: {report_id}")
