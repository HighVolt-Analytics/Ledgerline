"""Cash & liability outlook — 13-week forecast + AP ageing for CFO dashboard."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.bank_feed import BankTransaction
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.models.tenant import Tenant
from app.schemas.cash_liability_outlook import (
    ApAgeingBucket,
    CashLiabilityOutlookDashboard,
    CashLiabilityOutlookMeta,
    CashOutlookSummary,
    CashOutlookWeek,
)
from app.services.invoice.invoice_evaluation_service import ROUTE_TEAM
from app.services.reports.payables_catalog_builders import (
    _group_invoice_payments,
    _select_display_payment,
    ap_outstanding_rows,
)
from app.services.reports.statement_builders import _age_bucket
from app.services.shared.currency import convert_to_base
from app.tenant_settings import tenant_currency

_ZERO = Decimal("0.00")
_HORIZON_WEEKS = 13
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
_AGE_BUCKET_LABELS = ("Current", "1–30 days", "31–60 days", "61–90 days", "90+")
_AGE_BUCKET_KEYS = ("Current", "1–30", "31–60", "61–90", "90+")


@dataclass(frozen=True)
class _Flow:
    flow_date: date
    amount: Decimal
    category: str  # confirmed_ap | probable_ap | reimbursements | advances


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _week_label(week_start: date) -> str:
    return f"{week_start.day} {_MONTH_NAMES[week_start.month]}"


def _week_starts(as_of: date, weeks: int = _HORIZON_WEEKS) -> list[tuple[int, date, str]]:
    return [
        (i, as_of + timedelta(days=7 * i), _week_label(as_of + timedelta(days=7 * i)))
        for i in range(weeks)
    ]


def _week_index(flow_date: date, as_of: date) -> int:
    delta = (flow_date - as_of).days
    if delta < 0:
        return 0
    return min(delta // 7, _HORIZON_WEEKS - 1)


def _to_base(amount: Decimal, currency: str | None, *, base: str) -> Decimal:
    return _quantize(convert_to_base(amount, currency, base=base))


async def _opening_cash_balance(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    base: str,
) -> Decimal | None:
    """Latest running balance per bank account from imported bank feeds."""
    accounts = (
        await db.execute(
            select(BankTransaction.bank_account_id)
            .where(BankTransaction.tenant_id == tenant_id)
            .group_by(BankTransaction.bank_account_id)
        )
    ).all()
    if not accounts:
        return None
    total = _ZERO
    for (account_id,) in accounts:
        row = (
            await db.execute(
                select(BankTransaction.balance, BankTransaction.currency)
                .where(
                    BankTransaction.tenant_id == tenant_id,
                    BankTransaction.bank_account_id == account_id,
                    BankTransaction.balance.isnot(None),
                )
                .order_by(BankTransaction.txn_date.desc(), BankTransaction.id.desc())
                .limit(1)
            )
        ).first()
        if row is None or row[0] is None:
            continue
        total += _to_base(Decimal(str(row[0])), row[1], base=base)
    return _quantize(total) if total > 0 else None


async def _ap_flows(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    as_of: date,
) -> list[_Flow]:
    """Same cash-need definition as Payment Schedule / Cash Forecast reports."""
    remaining_by_id = {
        row.invoice_id: row.remaining
        for row in await ap_outstanding_rows(db, tenant_id, as_of)
        if row.remaining > 0
    }
    if not remaining_by_id:
        return []
    pay = aliased(Payment)
    stmt = (
        select(Invoice, pay)
        .outerjoin(
            pay,
            (pay.invoice_id == Invoice.id) & (pay.tenant_id == tenant_id),
        )
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.id.in_(list(remaining_by_id)),
        )
    )
    flows: list[_Flow] = []
    for invoice, payments in _group_invoice_payments((await db.execute(stmt)).all()):
        remaining = remaining_by_id.get(invoice.id)
        if remaining is None or remaining <= 0:
            continue
        amount = _quantize(remaining)
        display_pay = _select_display_payment(payments)
        flow_date = None
        confirmed = False
        if display_pay is not None and display_pay.scheduled_date is not None:
            flow_date = display_pay.scheduled_date
            confirmed = True
        elif invoice.due_date is not None:
            flow_date = invoice.due_date
        if flow_date is None:
            continue
        if flow_date < as_of:
            flow_date = as_of
        category = "confirmed_ap" if confirmed else "probable_ap"
        flows.append(_Flow(flow_date=flow_date, amount=amount, category=category))
    return flows


async def _team_expense_flows(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    as_of: date,
    *,
    base: str,
) -> list[_Flow]:
    """Scheduled team-expense payouts (reimbursements and advances)."""
    pay = aliased(Payment)
    stmt = (
        select(Invoice, pay)
        .join(
            pay,
            (pay.invoice_id == Invoice.id) & (pay.tenant_id == tenant_id),
        )
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.route_target == ROUTE_TEAM,
            pay.scheduled_date.isnot(None),
            pay.status == PaymentStatus.SCHEDULED,
            pay.scheduled_date >= as_of,
        )
    )
    flows: list[_Flow] = []
    for invoice, payment in (await db.execute(stmt)).all():
        if payment is None or payment.scheduled_date is None:
            continue
        amount = _to_base(
            Decimal(str(payment.amount or invoice.total or 0)),
            payment.currency or invoice.currency,
            base=base,
        )
        if amount <= 0:
            continue
        kind = (invoice.team_expense_kind or "").strip().lower()
        category = "advances" if kind == "advance" else "reimbursements"
        flows.append(
            _Flow(flow_date=payment.scheduled_date, amount=amount, category=category)
        )
    return flows


def _empty_weeks() -> dict[int, dict[str, Decimal]]:
    keys = (
        "confirmed_ap",
        "probable_ap",
        "recurring",
        "reimbursements",
        "advances",
        "tax",
    )
    return {i: {k: _ZERO for k in keys} for i in range(_HORIZON_WEEKS)}


async def _ap_ageing_buckets(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    as_of: date,
) -> tuple[list[ApAgeingBucket], Decimal]:
    totals = {key: _ZERO for key in _AGE_BUCKET_KEYS}
    grand = _ZERO
    for row in await ap_outstanding_rows(db, tenant_id, as_of):
        bucket = _age_bucket(row.due_date, as_of)
        amt = _quantize(row.remaining)
        totals[bucket] += amt
        grand += amt
    buckets = [
        ApAgeingBucket(bucket=label, amount=totals[key])
        for label, key in zip(_AGE_BUCKET_LABELS, _AGE_BUCKET_KEYS, strict=True)
    ]
    return buckets, _quantize(grand)


async def build_cash_liability_outlook_dashboard(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    environment_label: str | None = None,
) -> CashLiabilityOutlookDashboard:
    from app.services.reports.dashboard_service import _institution_today

    tenant = await db.get(Tenant, tenant_id)
    base = tenant_currency(tenant)
    as_of = await _institution_today(db, tenant_id)
    week_plan = _week_starts(as_of)
    buckets = _empty_weeks()

    for flow in await _ap_flows(db, tenant_id, as_of):
        idx = _week_index(flow.flow_date, as_of)
        buckets[idx][flow.category] += flow.amount

    for flow in await _team_expense_flows(db, tenant_id, as_of, base=base):
        idx = _week_index(flow.flow_date, as_of)
        buckets[idx][flow.category] += flow.amount

    opening_cash = await _opening_cash_balance(db, tenant_id, base=base)
    cumulative = _ZERO
    weeks_out: list[CashOutlookWeek] = []
    for idx, week_start, label in week_plan:
        row = buckets[idx]
        total = sum(row.values(), _ZERO)
        cumulative += total
        balance = None
        if opening_cash is not None:
            balance = _quantize(opening_cash - cumulative)
        weeks_out.append(
            CashOutlookWeek(
                week_start=week_start.isoformat(),
                label=label,
                confirmed_ap=_quantize(row["confirmed_ap"]),
                probable_ap=_quantize(row["probable_ap"]),
                recurring=_quantize(row["recurring"]),
                reimbursements=_quantize(row["reimbursements"]),
                advances=_quantize(row["advances"]),
                tax=_quantize(row["tax"]),
                total_outflow=_quantize(total),
                available_balance=balance,
            )
        )

    totals = [w.total_outflow for w in weeks_out]
    next_week = totals[0] if totals else _ZERO
    horizon_total = _quantize(sum(totals, _ZERO))
    peak = max(totals) if totals else _ZERO
    peak_label = weeks_out[totals.index(peak)].label if totals and peak > 0 else ""
    coverage = None
    if opening_cash is not None and next_week > 0:
        coverage = _quantize(opening_cash / next_week)

    ageing, ageing_total = await _ap_ageing_buckets(db, tenant_id, as_of)

    notes = [
        f"All amounts {base}.",
        "13-week horizon starts as-of date; each week is 7 days from the prior.",
        "Confirmed AP = posted remaining balance with a scheduled payment date.",
        "Probable AP = posted remaining balance projected on due date (no schedule).",
        "Overdue AP flows roll into week 1 (same as Cash Forecast report).",
        "Reimbursements / advances = scheduled team-expense payments only.",
        "Available balance = latest bank-feed running balance minus cumulative outflows "
        "(null when no bank feeds imported).",
        "AP ageing uses Aged Payables bucket definitions on netted ledger remaining.",
    ]
    coverage_gaps = [
        "recurring: no recurring-vendor register — stack shows 0 until configured.",
        "tax_bas: no BAS/tax payment schedule — stack shows 0 until configured.",
        "reimbursements_unscheduled: open reimbursement-due amounts without a scheduled "
        "payment are excluded (Cash Forecast notes the same gap).",
    ]

    return CashLiabilityOutlookDashboard(
        meta=CashLiabilityOutlookMeta(
            currency=base,
            as_of=as_of.isoformat(),
            horizon_weeks=_HORIZON_WEEKS,
            environment_label=environment_label,
            coverage_gaps=coverage_gaps,
            notes=notes,
        ),
        weeks=weeks_out,
        summary=CashOutlookSummary(
            next_week_outflow=next_week,
            total_horizon_outflow=horizon_total,
            peak_week_outflow=_quantize(peak),
            peak_week_label=peak_label,
            coverage_ratio=coverage,
            opening_cash_balance=opening_cash,
        ),
        ap_ageing=ageing,
        ap_ageing_total=ageing_total,
    )


async def ap_ageing_total_from_rows(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    as_of: date,
) -> Decimal:
    """Reconciliation helper — sum of ageing bucket amounts."""
    _buckets, total = await _ap_ageing_buckets(db, tenant_id, as_of)
    return total
