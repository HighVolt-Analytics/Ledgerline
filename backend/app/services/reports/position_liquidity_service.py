"""Position & Liquidity dashboard — reuses audited report definitions.

Each KPI is derived from the same query/report as its detail page so dashboard
figures reconcile with drill-down reports for the same period.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.services.approval.approval_board_service import approval_board_column_expr
from app.models.tenant import Tenant
from app.schemas.position_liquidity import (
    PositionLiquidityDashboard,
    PositionLiquidityKpis,
    PositionLiquidityMeta,
)
from app.services.approval.approval_quorum_service import quorum_met
from app.services.invoice.invoice_evaluation_service import (
    EVAL_PENDING_APPROVAL,
    ROUTE_TEAM,
)
from app.services.reports.dashboard_period import fy_window, resolve_dashboard_period
from app.services.reports.dashboard_service import _institution_today
from app.services.reports.exception_status_catalog_builders import (
    _parse_money,
    _preview_maps,
    build_control_centre,
)
from app.services.reports.payables_catalog_builders import (
    _paid_payment_amount,
    ap_outstanding_rows,
    ap_route_clause,
    approval_status,
    build_vendor_spend_summary,
)
from app.services.reports.report_catalog import CATALOG_BY_ID
from app.services.reports.statement_builders import (
    _build_aged,
    _build_budget_variance,
    _prior_window,
)
from app.services.reports.team_expense_catalog_builders import build_advance_aging
from app.services.reports.team_expense_reports_service import build_advance_settlement_rows
from app.services.shared.currency import convert_to_base
from app.tenant_settings import tenant_currency

_ZERO = Decimal("0.00")
_OVERDUE_AP_THRESHOLD_PCT = Decimal("10")
_MONTH_NAMES = (
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


@dataclass(frozen=True)
class _ApLine:
    invoice_id: int
    due_date: date | None
    remaining: Decimal
    currency: str
    approved: bool


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _pct(part: Decimal, whole: Decimal) -> Decimal | None:
    if whole == 0:
        return None
    return _quantize(part / whole * Decimal("100"))


def _to_base(amount: Decimal, currency: str | None, *, base: str) -> Decimal:
    return _quantize(convert_to_base(amount, currency, base=base))


def _fy_window(as_of: date) -> tuple[date, date, str]:
    """Back-compat alias — prefer resolve_dashboard_period / fy_window."""
    return fy_window(as_of)


def _due_bucket_days(due: date | None, as_of: date) -> int | None:
    if due is None:
        return None
    return (due - as_of).days


def _is_non_po_invoice(invoice: Invoice) -> bool:
    po_ref = (invoice.po_reference or "").strip()
    if po_ref:
        return False
    eval_status = (invoice.evaluation_status or "").strip().lower()
    if eval_status == "awaiting_po":
        return True
    route = (invoice.route_target or "").strip()
    if route and route not in {"", "purchase"}:
        return False
    kind = (invoice.purchase_document_type or "").strip().lower()
    if kind in {"po", "grn"}:
        return False
    return True


async def _ap_lines(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    as_of: date,
    *,
    base: str,
) -> list[_ApLine]:
    outstanding = await ap_outstanding_rows(db, tenant_id, as_of)
    if not outstanding:
        return []
    ids = [row.invoice_id for row in outstanding]
    invoices = {
        inv.id: inv
        for inv in (
            await db.execute(
                select(Invoice).where(
                    Invoice.tenant_id == tenant_id,
                    Invoice.id.in_(ids),
                )
            )
        ).scalars().all()
        if inv.id is not None
    }
    lines: list[_ApLine] = []
    for row in outstanding:
        inv = invoices.get(row.invoice_id)
        currency = (inv.currency if inv else None) or base
        approved = approval_status(inv) == "Approved" if inv is not None else False
        lines.append(
            _ApLine(
                invoice_id=row.invoice_id,
                due_date=row.due_date,
                remaining=_to_base(row.remaining, currency, base=base),
                currency=currency,
                approved=approved,
            )
        )
    return lines


def _sum_ap_buckets(lines: list[_ApLine], as_of: date) -> dict[str, Decimal]:
    total = _ZERO
    approved_not_paid = _ZERO
    due_7 = _ZERO
    due_14 = _ZERO
    due_30 = _ZERO
    overdue = _ZERO
    for line in lines:
        total += line.remaining
        if line.approved and line.remaining > 0:
            approved_not_paid += line.remaining
        days = _due_bucket_days(line.due_date, as_of)
        if days is None:
            continue
        if days < 0:
            overdue += line.remaining
        elif days <= 7:
            due_7 += line.remaining
        elif days <= 14:
            due_14 += line.remaining
        elif days <= 30:
            due_30 += line.remaining
    return {
        "ap_outstanding": total,
        "approved_not_paid": approved_not_paid,
        "due_7": due_7,
        "due_14": due_14,
        "due_30": due_30,
        "overdue": overdue,
    }


async def ap_outstanding_total_from_aged(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    as_of: date,
    *,
    base: str,
) -> Decimal:
    """Reconciliation helper — sum Balance Due from Aged Payables rows."""
    preview = await _build_aged(
        db, tenant_id, CATALOG_BY_ID["aged-payables"], as_of
    )
    balance_idx = preview.columns.index("Balance Due")
    total = _ZERO
    for row in preview.rows:
        if row.emphasize:
            continue
        total += _parse_money(row.cells[balance_idx])
    return _quantize(total)


async def _ap_balance_as_of(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    as_of: date,
    *,
    base: str,
) -> Decimal:
    lines = await _ap_lines(db, tenant_id, as_of, base=base)
    return sum((line.remaining for line in lines), _ZERO)


async def _purchases_for_period(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    *,
    base: str,
) -> Decimal:
    rows = (
        await db.execute(
            select(Invoice.total, Invoice.currency).where(
                Invoice.tenant_id == tenant_id,
                Invoice.status == InvoiceStatus.PROCESSED,
                ap_route_clause(),
                Invoice.invoice_date.is_not(None),
                Invoice.invoice_date >= start,
                Invoice.invoice_date <= end,
            )
        )
    ).all()
    return sum(
        (_to_base(Decimal(str(total or 0)), currency, base=base) for total, currency in rows),
        _ZERO,
    )


async def _compute_dpo(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    *,
    base: str,
) -> Decimal | None:
    days = (end - start).days + 1
    if days <= 0:
        return None
    start_bal = await _ap_balance_as_of(db, tenant_id, start, base=base)
    end_bal = await _ap_balance_as_of(db, tenant_id, end, base=base)
    avg_ap = (start_bal + end_bal) / Decimal("2")
    purchases = await _purchases_for_period(db, tenant_id, start, end, base=base)
    if purchases == 0:
        return None
    return _quantize(avg_ap / purchases * Decimal(days))


async def _on_time_payment_rate(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    *,
    base: str,
) -> Decimal | None:
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    rows = (
        await db.execute(
            select(Payment, Invoice.due_date, Invoice.currency)
            .join(Invoice, Invoice.id == Payment.invoice_id)
            .where(
                Payment.tenant_id == tenant_id,
                Invoice.tenant_id == tenant_id,
                Payment.status == PaymentStatus.PAID,
                Payment.paid_date.isnot(None),
                Payment.paid_date >= start_dt,
                Payment.paid_date < end_dt,
                Invoice.due_date.isnot(None),
                ap_route_clause(),
            )
        )
    ).all()
    paid_total = _ZERO
    on_time_total = _ZERO
    for payment, due_date, currency in rows:
        amount, _ = _paid_payment_amount(payment)
        if amount <= 0:
            continue
        converted = _to_base(amount, currency, base=base)
        paid_total += converted
        paid_day = payment.paid_date.date() if payment.paid_date else None
        if paid_day is not None and due_date is not None and paid_day <= due_date:
            on_time_total += converted
    return _pct(on_time_total, paid_total)


async def _budget_totals(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    *,
    base: str,
) -> tuple[Decimal, Decimal, Decimal, Decimal | None]:
    preview = await _build_budget_variance(
        db,
        tenant_id,
        CATALOG_BY_ID["budget-variance"],
        start,
        end,
        compare=False,
        as_of=True,
    )
    budget_idx = preview.columns.index("Budget")
    actual_idx = preview.columns.index("Actual")
    committed_idx = preview.columns.index("Committed")
    allocated = _ZERO
    actual = _ZERO
    committed = _ZERO
    for row in preview.rows:
        if row.emphasize:
            continue
        allocated += _parse_money(row.cells[budget_idx])
        actual += _parse_money(row.cells[actual_idx])
        committed += _parse_money(row.cells[committed_idx])
    utilisation = _pct(actual, allocated)
    return allocated, actual, committed, utilisation


async def _advance_totals(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    as_of: date,
    *,
    base: str,
) -> tuple[Decimal, Decimal, int]:
    settlement = await build_advance_settlement_rows(db, tenant_id)
    outstanding = sum(
        (Decimal(str(row.advance_ledger_balance or 0)) for row in settlement),
        _ZERO,
    )
    aging, _ = await build_advance_aging(
        db, tenant_id, CATALOG_BY_ID["advance-aging"], as_of
    )
    overdue = _ZERO
    employees: set[str] = set()
    for item in _preview_maps(aging):
        days = int(item.get("Days Outstanding", "0") or "0")
        if days <= 0:
            continue
        amt = _parse_money(item.get("Outstanding", "") or item.get("Total", ""))
        if amt <= 0:
            continue
        overdue += amt
        owner = (item.get("Employee", "") or "").strip()
        if owner:
            employees.add(owner)
    return outstanding, overdue, len(employees)


async def _open_exceptions(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    *,
    base: str,
) -> tuple[int, Decimal]:
    preview = await build_control_centre(
        db,
        tenant_id,
        CATALOG_BY_ID["control-centre"],
        start,
        end,
        as_of=True,
    )
    amount_idx = preview.columns.index("Amount")
    count = 0
    at_risk = _ZERO
    for item in _preview_maps(preview):
        count += 1
        at_risk += _parse_money(item.get("Amount", ""))
    return count, _quantize(at_risk)


async def _document_board_totals(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    base: str,
) -> tuple[int, Decimal, int, Decimal]:
    """Upload matrix approval-board columns (To Review / Processing)."""
    col = approval_board_column_expr()
    review_count = 0
    review_value = _ZERO
    processing_count = 0
    processing_value = _ZERO
    rows = (
        await db.execute(
            select(
                col.label("board"),
                func.count(Invoice.id),
                Invoice.currency,
                func.coalesce(func.sum(Invoice.total), 0),
            )
            .where(Invoice.tenant_id == tenant_id)
            .group_by(col, Invoice.currency)
        )
    ).all()
    for board, count, currency, total in rows:
        key = str(board or "")
        amount = _to_base(Decimal(str(total or 0)), currency, base=base)
        item_count = int(count or 0)
        if key == "review":
            review_count += item_count
            review_value += amount
        elif key == "processing":
            processing_count += item_count
            processing_value += amount
    return (
        review_count,
        _quantize(review_value),
        processing_count,
        _quantize(processing_value),
    )


async def _payments_queue_totals(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    base: str,
) -> tuple[int, Decimal]:
    """Payments module open queue — same statuses as Payments workspace."""
    open_statuses = (
        PaymentStatus.QUEUE,
        PaymentStatus.AWAITING,
        PaymentStatus.SCHEDULED,
    )
    count = (
        await db.execute(
            select(func.count(Payment.id)).where(
                Payment.tenant_id == tenant_id,
                Payment.status.in_(open_statuses),
            )
        )
    ).scalar() or 0
    rows = (
        await db.execute(
            select(
                Payment.currency,
                func.coalesce(func.sum(Payment.amount), 0),
            )
            .where(
                Payment.tenant_id == tenant_id,
                Payment.status.in_(open_statuses),
            )
            .group_by(Payment.currency)
        )
    ).all()
    value = sum(
        (_to_base(Decimal(str(amount or 0)), currency, base=base) for currency, amount in rows),
        _ZERO,
    )
    return int(count), _quantize(value)


async def _claims_pending(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    base: str,
) -> tuple[int, Decimal]:
    rows = (
        await db.execute(
            select(Invoice).where(
                Invoice.tenant_id == tenant_id,
                Invoice.route_target == ROUTE_TEAM,
                Invoice.evaluation_status == EVAL_PENDING_APPROVAL,
                Invoice.status.notin_(
                    [InvoiceStatus.REJECTED, InvoiceStatus.DUPLICATE_SKIPPED]
                ),
            )
        )
    ).scalars().all()
    pending: list[Invoice] = []
    for inv in rows:
        if quorum_met(inv.approval_chain):
            continue
        pending.append(inv)
    total_value = sum(
        (
            _to_base(Decimal(str(inv.total or 0)), inv.currency, base=base)
            for inv in pending
        ),
        _ZERO,
    )
    return len(pending), _quantize(total_value)


async def _vendor_concentration(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    *,
    base: str,
) -> tuple[Decimal | None, Decimal | None]:
    preview = await build_vendor_spend_summary(
        db,
        tenant_id,
        CATALOG_BY_ID["vendor-spend-summary"],
        start,
        end,
        as_of=True,
    )
    invoiced_idx = preview.columns.index("Total Invoiced")
    vendor_spend: dict[str, Decimal] = {}
    for row in preview.rows:
        if row.emphasize:
            continue
        vendor = row.cells[0]
        if vendor.upper() == "TOTAL":
            continue
        vendor_spend[vendor] = _parse_money(row.cells[invoiced_idx])
    if not vendor_spend:
        return None, None
    total_spend = sum(vendor_spend.values(), _ZERO)
    top10 = sum(
        sorted(vendor_spend.values(), reverse=True)[:10],
        _ZERO,
    )
    concentration = _pct(top10, total_spend)

    invoices = (
        await db.execute(
            select(Invoice).where(
                Invoice.tenant_id == tenant_id,
                ap_route_clause(),
                Invoice.invoice_date.is_not(None),
                Invoice.invoice_date <= end,
            )
        )
    ).scalars().all()
    non_po = _ZERO
    all_spend = _ZERO
    for inv in invoices:
        amt = _to_base(Decimal(str(inv.total or 0)), inv.currency, base=base)
        if amt <= 0:
            continue
        all_spend += amt
        if _is_non_po_invoice(inv):
            non_po += amt
    non_po_pct = _pct(non_po, all_spend)
    return concentration, non_po_pct


async def build_position_liquidity_dashboard(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    environment_label: str | None = None,
    period: str | None = None,
) -> PositionLiquidityDashboard:
    tenant = await db.get(Tenant, tenant_id)
    base = tenant_currency(tenant)
    as_of = await _institution_today(db, tenant_id)
    period_start, period_end, period_label = resolve_dashboard_period(period, as_of)

    ap_lines = await _ap_lines(db, tenant_id, as_of, base=base)
    ap_buckets = _sum_ap_buckets(ap_lines, as_of)
    overdue_pct = _pct(ap_buckets["overdue"], ap_buckets["ap_outstanding"])

    dpo = await _compute_dpo(db, tenant_id, period_start, period_end, base=base)
    prior_start, prior_end = _prior_window(period_start, period_end)
    dpo_prior = await _compute_dpo(db, tenant_id, prior_start, prior_end, base=base)

    on_time = await _on_time_payment_rate(
        db, tenant_id, period_start, period_end, base=base
    )
    budget_allocated, budget_actual, budget_committed, utilisation = await _budget_totals(
        db, tenant_id, period_start, period_end, base=base
    )
    advances_out, advances_overdue, advances_employees = await _advance_totals(
        db, tenant_id, as_of, base=base
    )
    exceptions_count, exceptions_risk = await _open_exceptions(
        db, tenant_id, period_start, period_end, base=base
    )
    claims_count, claims_value = await _claims_pending(db, tenant_id, base=base)
    (
        review_count,
        review_value,
        processing_count,
        processing_value,
    ) = await _document_board_totals(db, tenant_id, base=base)
    payments_count, payments_value = await _payments_queue_totals(
        db, tenant_id, base=base
    )
    top10_pct, non_po_pct = await _vendor_concentration(
        db, tenant_id, period_start, period_end, base=base
    )

    notes: list[str] = [
        f"All figures {base}, consolidated.",
        "AP balances use netted ledger truth (sum credit − debit on AP control), "
        "same as Aged Payables.",
        "Due buckets use non-overlapping windows: [0,7], (7,14], (14,30] days from as-of.",
        f"Overdue threshold {_OVERDUE_AP_THRESHOLD_PCT}% is a default covenant constant "
        "(not yet tenant-configurable).",
        "Budget utilisation compares Actual to Allocated only; Committed (in-flight TE "
        "claims) is excluded from the headline % — see Budget Variance for encumbrance.",
        "Open exceptions = Control Centre row count (live rule evaluation, de-duplicated).",
        "To Review / Processing use the Upload matrix approval-board columns "
        "(same mapping as All Documents status filter).",
        "Payments queue = open disbursements (queued, awaiting approval, scheduled).",
        "Approved not paid = AP approved in ledger but not yet paid (Payments release).",
        "DPO and on-time payment rate remain in the API for reports but are not headline cards.",
        "Discount capture requires structured payment-term discount data — not tracked yet.",
    ]
    coverage_gaps = [
        "bank_detail_change_before_payment: excluded from Open exceptions until a "
        "dedicated register exists (Control Centre omits it by design; DT-23 bank-change "
        "documents are tracked separately on the dashboard risk panel only).",
        "discount_capture: no structured vendor discount-term data — card shows honest gap.",
    ]

    return PositionLiquidityDashboard(
        meta=PositionLiquidityMeta(
            currency=base,
            period_label=period_label,
            as_of=as_of.isoformat(),
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            environment_label=environment_label,
            coverage_gaps=coverage_gaps,
            notes=notes,
        ),
        kpis=PositionLiquidityKpis(
            ap_outstanding=ap_buckets["ap_outstanding"],
            approved_not_paid=ap_buckets["approved_not_paid"],
            due_next_7_days=ap_buckets["due_7"],
            due_next_14_days=ap_buckets["due_14"],
            due_next_30_days=ap_buckets["due_30"],
            overdue=ap_buckets["overdue"],
            overdue_pct=overdue_pct,
            overdue_threshold_pct=_OVERDUE_AP_THRESHOLD_PCT,
            dpo_days=dpo,
            dpo_prior_year_days=dpo_prior,
            on_time_payment_rate_pct=on_time,
            discount_capture_rate_pct=None,
            budget_utilisation_pct=utilisation,
            budget_actual=budget_actual,
            budget_allocated=budget_allocated,
            budget_committed=budget_committed,
            advances_outstanding=advances_out,
            advances_overdue=advances_overdue,
            advances_overdue_employees=advances_employees,
            open_exceptions_count=exceptions_count,
            open_exceptions_at_risk=exceptions_risk,
            claims_pending_count=claims_count,
            claims_pending_value=claims_value,
            documents_to_review_count=review_count,
            documents_to_review_value=review_value,
            documents_processing_count=processing_count,
            documents_processing_value=processing_value,
            payments_queue_count=payments_count,
            payments_queue_value=payments_value,
            vendor_top10_concentration_pct=top10_pct,
            vendor_non_po_spend_pct=non_po_pct,
        ),
    )
