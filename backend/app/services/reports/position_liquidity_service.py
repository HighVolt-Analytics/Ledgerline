"""Position & Liquidity dashboard — report-sourced KPIs (no FX rollup for register tiles).

Tile sources (do not reconcile AP Outstanding with Overdue — different reports by design):
  1. AP Outstanding — Invoice Register unpaid (Payment Date empty), per-currency SUM(Total)
  2. Due next 7 days — same unpaid set, due in [as_of, as_of+7], per-currency SUM(Total)
  3. Overdue — Aged Payables buckets 1–30 / 31–60 / 61–90 / 90+ (Balance Due)
  4. Approved · awaiting payment — Uploads Summary: Action=Approved + Payment Auth=Awaiting Payment
  5. Documents in pipeline — approval_board To Review count only
  6. Payments queue — COUNT of same rows as #4
  7. Budget utilisation — average of Budget vs Actual `% Utilise` (skip blank/-)
  8. Open exceptions — Invoice Exception report row count
  9. Expense claims pending — Claim Status where Status/Reason != Approved
 10. Employee advances — Advance Aging Outstanding across all age buckets
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.models.tenant import Tenant
from app.schemas.position_liquidity import (
    CurrencyAmount,
    PositionLiquidityDashboard,
    PositionLiquidityKpis,
    PositionLiquidityMeta,
)
from app.services.approval.approval_board_service import (
    approval_board_column,
    approval_board_column_expr,
)
from app.services.reports.dashboard_period import fy_window, resolve_dashboard_period
from app.services.reports.dashboard_service import _institution_today
from app.services.reports.exception_status_catalog_builders import (
    _parse_money,
    _preview_maps,
    build_claim_status,
    build_invoice_exception,
)
from app.services.reports.matrix_service import derive_matrix_payment_status
from app.services.reports.payables_catalog_builders import (
    _group_invoice_payments,
    _paid_payment_amount,
    _register_window,
    _select_display_payment,
    ap_outstanding_rows,
    ap_route_clause,
    build_vendor_spend_summary,
)
from app.services.reports.report_catalog import CATALOG_BY_ID
from app.services.reports.statement_builders import (
    _build_aged,
    _build_budget_variance,
    _prior_window,
)
from app.services.reports.team_expense_catalog_builders import build_advance_aging
from app.services.shared.currency import convert_to_base
from app.tenant_settings import tenant_currency

_ZERO = Decimal("0.00")
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
_OVERDUE_BUCKETS = ("1–30", "31–60", "61–90", "90+")
# TODO(confirm-schema): sheet said 1–30 / 31–60 / 60+; report uses 0–30 / 31–60 / 61–90 / 90+
_ADVANCE_BUCKETS = ("0–30", "31–60", "61–90", "90+")


@dataclass(frozen=True)
class _RegisterLine:
    due_date: date | None
    currency: str
    total: Decimal


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


def _currency_code(raw: str | None) -> str:
    """Native currency only — blank stays blank (do not invent AUD/USD/base)."""
    return (raw or "").strip().upper()


def _currency_amounts(totals: dict[str, Decimal]) -> list[CurrencyAmount]:
    return [
        CurrencyAmount(currency=code, amount=_quantize(amount))
        for code, amount in sorted(totals.items())
        if amount != 0
    ]


def _parse_utilise_pct(raw: str | None) -> Decimal | None:
    text = (raw or "").strip()
    if not text or text == "-":
        return None
    if text.endswith("%"):
        text = text[:-1].strip()
    try:
        return Decimal(text)
    except Exception:
        return None


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


async def _unpaid_register_lines(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    as_of: date,
    *,
    base: str,
) -> list[_RegisterLine]:
    """Invoice Register rows with Payment Date empty — native currency totals (no FX).

    # TODO(confirm-schema): Uploads Summary Module ∈ {Exp Mgt, Purchase Mgt}
    # mapped to Invoice Register unpaid + ap_route_clause().
    # TODO(confirm-schema): Amount Due mapped to register Total.
    """
    date_clause, _ = _register_window(as_of, as_of, as_of=True)
    pay = aliased(Payment)
    stmt = (
        select(Invoice, pay)
        .outerjoin(
            pay,
            (pay.invoice_id == Invoice.id) & (pay.tenant_id == tenant_id),
        )
        .where(
            Invoice.tenant_id == tenant_id,
            ap_route_clause(),
            date_clause,
        )
        .order_by(Invoice.invoice_date, Invoice.id)
    )
    lines: list[_RegisterLine] = []
    for invoice, payments in _group_invoice_payments((await db.execute(stmt)).all()):
        payment = _select_display_payment(payments)
        if payment is not None and payment.paid_date is not None:
            continue
        lines.append(
            _RegisterLine(
                due_date=invoice.due_date,
                currency=_currency_code(invoice.currency),
                total=_quantize(Decimal(str(invoice.total or 0))),
            )
        )
    return lines


def _sum_register_by_currency(
    lines: list[_RegisterLine],
    *,
    predicate,
) -> list[CurrencyAmount]:
    totals: dict[str, Decimal] = {}
    for line in lines:
        if not predicate(line):
            continue
        totals[line.currency] = totals.get(line.currency, _ZERO) + line.total
    return _currency_amounts(totals)


async def _uploads_approved_awaiting_payment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    base: str,
) -> tuple[list[CurrencyAmount], int]:
    """Uploads Summary: Action=Approved (board) and Payment Auth=Awaiting Payment.

    Amount = native invoice.total per currency (no FX). Same row set drives
    Approved · awaiting payment (sum) and Payments queue (count).
    """
    pay = aliased(Payment)
    stmt = (
        select(Invoice, pay)
        .outerjoin(
            pay,
            (pay.invoice_id == Invoice.id) & (pay.tenant_id == tenant_id),
        )
        .where(Invoice.tenant_id == tenant_id)
        .order_by(Invoice.id)
    )
    totals: dict[str, Decimal] = {}
    count = 0
    for invoice, payments in _group_invoice_payments((await db.execute(stmt)).all()):
        # Action column / Upload status filter "Approved"
        if approval_board_column(invoice) != "approved":
            continue
        payment = _select_display_payment(payments)
        # Payment auth column
        if derive_matrix_payment_status(invoice, payment) != "Awaiting Payment":
            continue
        currency = _currency_code(invoice.currency)
        totals[currency] = totals.get(currency, _ZERO) + _quantize(
            Decimal(str(invoice.total or 0))
        )
        count += 1
    return _currency_amounts(totals), count


async def _overdue_aged_buckets(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    as_of: date,
) -> dict[str, Decimal]:
    preview = await _build_aged(
        db, tenant_id, CATALOG_BY_ID["aged-payables"], as_of
    )
    bucket_idx = {name: preview.columns.index(name) for name in _OVERDUE_BUCKETS}
    totals = {name: _ZERO for name in _OVERDUE_BUCKETS}
    for row in preview.rows:
        if row.emphasize:
            continue
        for name, idx in bucket_idx.items():
            totals[name] += _parse_money(row.cells[idx])
    return {name: _quantize(totals[name]) for name in _OVERDUE_BUCKETS}


async def _budget_utilisation_avg(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
) -> Decimal | None:
    preview = await _build_budget_variance(
        db,
        tenant_id,
        CATALOG_BY_ID["budget-variance"],
        start,
        end,
        compare=False,
        as_of=True,
    )
    utilise_idx = preview.columns.index("% Utilise")
    values: list[Decimal] = []
    for row in preview.rows:
        if row.emphasize:
            continue
        pct = _parse_utilise_pct(row.cells[utilise_idx])
        if pct is None:
            continue
        values.append(pct)
    if not values:
        return None
    return _quantize(sum(values, _ZERO) / Decimal(len(values)))


async def _advance_outstanding_total(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    as_of: date,
) -> Decimal:
    aging, _ = await build_advance_aging(
        db, tenant_id, CATALOG_BY_ID["advance-aging"], as_of
    )
    total = _ZERO
    for item in _preview_maps(aging):
        # Prefer Outstanding column; fall back to summing age bucket cells.
        outstanding = _parse_money(item.get("Outstanding", "") or "")
        if outstanding > 0:
            total += outstanding
            continue
        for bucket in _ADVANCE_BUCKETS:
            total += _parse_money(item.get(bucket, "") or "")
    return _quantize(total)


async def _open_invoice_exceptions(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
) -> int:
    preview = await build_invoice_exception(
        db,
        tenant_id,
        CATALOG_BY_ID["invoice-exception"],
        start,
        end,
    )
    return len(_preview_maps(preview))


async def _claims_pending_count(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
) -> int:
    # TODO(confirm-schema): literal Status/Reason != "Approved" includes
    # Rejected / Duplicate skipped — intentional per sheet.
    preview = await build_claim_status(
        db,
        tenant_id,
        CATALOG_BY_ID["claim-status"],
        start,
        end,
        as_of=True,
    )
    count = 0
    for item in _preview_maps(preview):
        status = (item.get("Status / Reason", "") or "").strip()
        if status != "Approved":
            count += 1
    return count


async def _documents_to_review_count(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> int:
    col = approval_board_column_expr()
    count = (
        await db.execute(
            select(func.count(Invoice.id)).where(
                Invoice.tenant_id == tenant_id,
                col == "review",
            )
        )
    ).scalar() or 0
    return int(count)


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
    """Ledger AP remaining in base currency — used for DPO only."""
    outstanding = await ap_outstanding_rows(db, tenant_id, as_of)
    if not outstanding:
        return _ZERO
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
    total = _ZERO
    for row in outstanding:
        inv = invoices.get(row.invoice_id)
        currency = (inv.currency if inv else None) or base
        total += _to_base(row.remaining, currency, base=base)
    return total


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

    register_lines = await _unpaid_register_lines(db, tenant_id, as_of, base=base)
    ap_by_ccy = _sum_register_by_currency(register_lines, predicate=lambda _: True)
    due_end = as_of + timedelta(days=7)
    due7_by_ccy = _sum_register_by_currency(
        register_lines,
        predicate=lambda line: (
            line.due_date is not None and as_of <= line.due_date <= due_end
        ),
    )
    approved_by_ccy, payments_queue_count = await _uploads_approved_awaiting_payment(
        db, tenant_id, base=base
    )

    overdue_buckets = await _overdue_aged_buckets(db, tenant_id, as_of)
    overdue_total = _quantize(sum(overdue_buckets.values(), _ZERO))

    dpo = await _compute_dpo(db, tenant_id, period_start, period_end, base=base)
    prior_start, prior_end = _prior_window(period_start, period_end)
    dpo_prior = await _compute_dpo(db, tenant_id, prior_start, prior_end, base=base)
    on_time = await _on_time_payment_rate(
        db, tenant_id, period_start, period_end, base=base
    )
    utilisation = await _budget_utilisation_avg(
        db, tenant_id, period_start, period_end
    )
    advances_out = await _advance_outstanding_total(db, tenant_id, as_of)
    exceptions_count = await _open_invoice_exceptions(
        db, tenant_id, period_start, period_end
    )
    claims_count = await _claims_pending_count(
        db, tenant_id, period_start, period_end
    )
    review_count = await _documents_to_review_count(db, tenant_id)
    top10_pct, non_po_pct = await _vendor_concentration(
        db, tenant_id, period_start, period_end, base=base
    )

    notes: list[str] = [
        f"Reporting currency label {base}; Invoice Register money tiles are "
        "per-currency native totals (no FX conversion).",
        "AP Outstanding / Due next 7 read Invoice Register unpaid rows — they need "
        "not reconcile with Overdue (Aged Payables journal remaining).",
        "Approved · awaiting payment / Payments queue = Uploads Summary rows where "
        "Action (approval board) is Approved and Payment Auth is Awaiting Payment "
        "(native per-currency Amount sum / count).",
        "Due next 7 days = due_date in [as_of, as_of+7] (already-overdue excluded).",
        "Overdue = Aged Payables Balance Due in 1–30 / 31–60 / 61–90 / 90+.",
        "Documents in pipeline = To Review count only (Processing excluded).",
        "Budget utilisation = simple average of % Utilise (blank/- rows excluded).",
        "Open exceptions = Invoice Exception report row count only.",
        # TODO(confirm-schema): claims Status/Reason != Approved includes Rejected/Duplicate
        "Claims pending = Claim Status rows where Status/Reason != Approved.",
        "Employee advances = Advance Aging Outstanding across all age buckets.",
        "DPO and on-time payment rate remain in the API for reports but are not headline cards.",
        "Discount capture requires structured payment-term discount data — not tracked yet.",
    ]
    coverage_gaps = [
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
            ap_outstanding_by_currency=ap_by_ccy,
            approved_not_paid_by_currency=approved_by_ccy,
            due_next_7_days_by_currency=due7_by_ccy,
            overdue=overdue_total,
            overdue_1_30=overdue_buckets["1–30"],
            overdue_31_60=overdue_buckets["31–60"],
            overdue_61_90=overdue_buckets["61–90"],
            overdue_90_plus=overdue_buckets["90+"],
            dpo_days=dpo,
            dpo_prior_year_days=dpo_prior,
            on_time_payment_rate_pct=on_time,
            discount_capture_rate_pct=None,
            budget_utilisation_pct=utilisation,
            advances_outstanding=advances_out,
            open_exceptions_count=exceptions_count,
            claims_pending_count=claims_count,
            documents_to_review_count=review_count,
            payments_queue_count=payments_queue_count,
            vendor_top10_concentration_pct=top10_pct,
            vendor_non_po_spend_pct=non_po_pct,
        ),
    )
