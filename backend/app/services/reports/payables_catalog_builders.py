"""Invoice-to-Pay catalog builders (AP invoices + payments)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry
from app.models.payment import Payment, PaymentStatus
from app.models.tenant import Tenant
from app.schemas.report_catalog import ReportPreview, ReportPreviewRow
from app.services.invoice.invoice_evaluation_service import (
    EVAL_PENDING_APPROVAL,
    ROUTE_SALES,
    ROUTE_TEAM,
    ROUTE_VAULT,
    load_posting_config_for_tenant,
)
from app.services.master_data.party_coa_subledger_service import control_account_codes_for_parent
from app.services.reports.report_catalog import ReportDefinition
from app.services.rule_book.rule_book_mapper import get_payable_account_mapping
from app.tenant_settings import tenant_currency

_ZERO = Decimal("0.00")
_EXCLUDED_AP_ROUTES = (ROUTE_TEAM, ROUTE_SALES, ROUTE_VAULT)
_CASH_FORECAST_NOTES = "Employee reimbursements are not included yet."
_VENDOR_SPEND_NULL_PAID_NOTES = (
    "One or more PAID payment rows had no amount and were counted as 0, not as the invoice total."
)
_VENDOR_SPEND_PACK_NOTES = (
    "Totals per vendor. Figures come from Invoice Register — vendor names must match exactly."
)


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


def ap_route_clause():
    """Vendor AP invoices.

    Unset or empty route_target is treated as AP (the product default). Only
    Team Expenses, Sales, and Vault are excluded.
    """
    return or_(
        Invoice.route_target.is_(None),
        Invoice.route_target == "",
        Invoice.route_target.notin_(_EXCLUDED_AP_ROUTES),
    )


@dataclass(frozen=True)
class ApOutstandingRow:
    invoice_id: int
    vendor: str | None
    due_date: date | None
    invoice_date: date | None
    invoice_no: str | None
    document_ref: str | None
    invoice_total: Decimal
    remaining: Decimal


async def ap_outstanding_rows(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    as_of: date,
) -> list[ApOutstandingRow]:
    """Posted AP remaining = sum(credit − debit) on the payable control account.

    Zero remaining is omitted. Negative remaining (over-credited) is kept so
    Aged Payables can show credit balances. Payment Schedule and Cash Forecast
    skip remaining <= 0 themselves.
    """
    config = await load_posting_config_for_tenant(db, tenant_id)
    mapping = get_payable_account_mapping(config)
    codes = control_account_codes_for_parent(config, mapping)
    balance_expr = func.coalesce(func.sum(JournalEntry.credit - JournalEntry.debit), 0)
    stmt = (
        select(
            Invoice.id,
            Invoice.vendor,
            Invoice.due_date,
            Invoice.invoice_date,
            Invoice.invoice_no,
            Invoice.document_ref,
            Invoice.total,
            balance_expr.label("balance"),
        )
        .join(Invoice, Invoice.id == JournalEntry.invoice_id)
        .where(
            JournalEntry.tenant_id == tenant_id,
            Invoice.tenant_id == tenant_id,
            JournalEntry.date <= as_of,
            Invoice.status == InvoiceStatus.PROCESSED,
            ap_route_clause(),
        )
        .group_by(
            Invoice.id,
            Invoice.vendor,
            Invoice.due_date,
            Invoice.invoice_date,
            Invoice.invoice_no,
            Invoice.document_ref,
            Invoice.total,
        )
    )
    if codes:
        stmt = stmt.where(JournalEntry.account_code.in_(codes))
    out: list[ApOutstandingRow] = []
    for row in (await db.execute(stmt)).all():
        remaining = Decimal(str(row.balance or 0))
        if remaining == 0:
            continue
        out.append(
            ApOutstandingRow(
                invoice_id=row.id,
                vendor=row.vendor,
                due_date=row.due_date,
                invoice_date=row.invoice_date,
                invoice_no=row.invoice_no,
                document_ref=row.document_ref,
                invoice_total=Decimal(str(row.total or 0)),
                remaining=remaining,
            )
        )
    return out


def last_approval(chain: object | None) -> tuple[str, str]:
    if not isinstance(chain, dict):
        return "", ""
    approvals = chain.get("approvals")
    if not isinstance(approvals, list) or not approvals:
        return "", ""
    last = approvals[-1]
    if not isinstance(last, dict):
        return "", ""
    at = last.get("at")
    at_s = ""
    if isinstance(at, str) and at:
        at_s = at[:10]
    return _text(last.get("name")), at_s


def approval_status(invoice: Invoice) -> str:
    eval_status = (invoice.evaluation_status or "").strip().lower()
    if eval_status == EVAL_PENDING_APPROVAL:
        return "Pending approval"
    name, _ = last_approval(invoice.approval_chain)
    if name:
        return "Approved"
    return _text(getattr(invoice.status, "value", invoice.status)) or ""


def due_bucket(due: date | None, as_of: date) -> str:
    if due is None:
        return "Upcoming"
    days = (due - as_of).days
    if days < 0:
        return "Overdue"
    if days <= 7:
        return "Due within 7 days"
    return "Upcoming"


def days_to_due(due: date | None, as_of: date) -> int | None:
    """Due date minus as-at date. Negative means overdue."""
    if due is None:
        return None
    return (due - as_of).days


def timing_label(due: date | None, as_of: date) -> str:
    bucket = due_bucket(due, as_of)
    return "OVERDUE" if bucket == "Overdue" else bucket


def _group_invoice_payments(
    rows: Sequence[tuple[Invoice, Payment | None]],
) -> list[tuple[Invoice, list[Payment]]]:
    """Collapse outer-join duplicates so one invoice is not counted twice."""
    grouped: dict[int, tuple[Invoice, list[Payment]]] = {}
    order: list[int] = []
    for invoice, payment in rows:
        invoice_id = invoice.id
        if invoice_id not in grouped:
            grouped[invoice_id] = (invoice, [])
            order.append(invoice_id)
        if payment is not None and all(existing.id != payment.id for existing in grouped[invoice_id][1]):
            grouped[invoice_id][1].append(payment)
    return [grouped[invoice_id] for invoice_id in order]


def _select_display_payment(payments: Sequence[Payment]) -> Payment | None:
    if not payments:
        return None
    paid = [row for row in payments if row.status == PaymentStatus.PAID]
    pool = paid or list(payments)
    return max(pool, key=lambda row: row.id or 0)


def _paid_payment_amount(payment: Payment) -> tuple[Decimal, bool]:
    """Paid cash to add, and whether amount was missing.

    Never falls back to the invoice total. Decimal('0') is a real zero payment;
    None is a data gap counted as 0 and flagged.
    """
    if payment.amount is None:
        return _ZERO, True
    return Decimal(str(payment.amount)), False


def _vendor_group_key(vendor: str | None) -> tuple[str, str]:
    display = (vendor or "Unregistered").strip() or "Unregistered"
    return display.casefold(), display


async def _currency(db: AsyncSession, tenant_id: uuid.UUID) -> str:
    tenant = await db.get(Tenant, tenant_id)
    return tenant_currency(tenant)


def _period_label(start: date, end: date) -> str:
    if start == end:
        return start.isoformat()
    return f"{start.isoformat()} – {end.isoformat()}"


def _register_window(start: date, end: date, *, as_of: bool):
    """Month/quarter = as-at end (same invoices as Invoice Register). Custom = invoice-date slice."""
    if as_of:
        return (
            or_(Invoice.invoice_date.is_(None), Invoice.invoice_date <= end),
            f"As of {end.isoformat()}",
        )
    return (
        Invoice.invoice_date.is_not(None)
        & (Invoice.invoice_date >= start)
        & (Invoice.invoice_date <= end),
        _period_label(start, end),
    )


def _summary_money(value: Decimal) -> str:
    if value == 0:
        return "-"
    return _money(value)


async def build_payment_schedule(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    definition: ReportDefinition,
    as_of: date,
) -> ReportPreview:
    currency = await _currency(db, tenant_id)
    # Posted remaining AP only. Unposted AP is excluded because
    # ensure_payment_for_invoice refuses status != PROCESSED; loosening that
    # guard reopens a Schedule/Forecast cash-need blind spot.
    remaining_by_id = {
        row.invoice_id: row.remaining
        for row in await ap_outstanding_rows(db, tenant_id, as_of)
        if row.remaining > 0
    }
    columns = [
        "Vendor",
        "Invoice No",
        "Due Date",
        "Amount Due",
        "Approval Status",
        "Scheduled Pay Date",
        "Days to Due",
        "Timing",
        "Notes",
    ]

    def _notes(overdue_total: Decimal, soon_total: Decimal) -> str:
        return (
            f"Overdue total: {_summary_money(overdue_total)}. "
            f"Due within 7 days: {_summary_money(soon_total)}."
        )

    if not remaining_by_id:
        return _preview(
            definition,
            period_label=f"As of {as_of.isoformat()}",
            currency=currency,
            columns=columns,
            rows=[],
            notes=_notes(_ZERO, _ZERO),
        )
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
            Invoice.due_date.is_not(None),
        )
        .order_by(Invoice.due_date, Invoice.id)
    )
    rows_out: list[ReportPreviewRow] = []
    overdue_total = _ZERO
    soon_total = _ZERO
    for invoice, payments in _group_invoice_payments((await db.execute(stmt)).all()):
        remaining = remaining_by_id.get(invoice.id)
        if remaining is None or remaining <= 0:
            continue
        due = invoice.due_date
        timing = timing_label(due, as_of)
        if timing == "OVERDUE":
            overdue_total += remaining
        elif timing == "Due within 7 days":
            soon_total += remaining
        payment = _select_display_payment(payments)
        scheduled = ""
        if payment is not None and payment.scheduled_date is not None:
            scheduled = payment.scheduled_date.isoformat()
        days = days_to_due(due, as_of)
        rows_out.append(
            _cell_row(
                invoice.vendor or "",
                invoice.invoice_no or "",
                due.isoformat() if due else "",
                _money(remaining),
                approval_status(invoice),
                scheduled,
                "" if days is None else str(days),
                timing,
                "",
            )
        )
    return _preview(
        definition,
        period_label=f"As of {as_of.isoformat()}",
        currency=currency,
        columns=columns,
        rows=rows_out,
        notes=_notes(overdue_total, soon_total),
    )


async def build_invoice_register(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    definition: ReportDefinition,
    start: date,
    end: date,
    *,
    as_of: bool = False,
) -> ReportPreview:
    currency = await _currency(db, tenant_id)
    date_clause, period_label = _register_window(start, end, as_of=as_of)
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
    rows_out: list[ReportPreviewRow] = []
    for invoice, payments in _group_invoice_payments((await db.execute(stmt)).all()):
        approver, approved_on = last_approval(invoice.approval_chain)
        payment = _select_display_payment(payments)
        paid_on = ""
        paid_ref = ""
        if payment is not None:
            if payment.paid_date is not None:
                paid_on = payment.paid_date.date().isoformat()
            paid_ref = _text(payment.payment_intent)
        rows_out.append(
            _cell_row(
                invoice.vendor or "",
                invoice.invoice_no or "",
                invoice.invoice_date.isoformat() if invoice.invoice_date else "",
                invoice.due_date.isoformat() if invoice.due_date else "",
                _money(Decimal(str(invoice.subtotal or 0))),
                _money(Decimal(str(invoice.gst or 0))),
                _money(Decimal(str(invoice.total or 0))),
                approval_status(invoice),
                approver,
                approved_on,
                paid_on,
                paid_ref,
            )
        )
    return _preview(
        definition,
        period_label=period_label,
        currency=currency,
        columns=[
            "Vendor",
            "Invoice No",
            "Invoice Date",
            "Due Date",
            "Amount (excl. tax)",
            "Tax / GST",
            "Total",
            "Status",
            "Approver",
            "Approval Date",
            "Payment Date",
            "Payment Ref",
        ],
        rows=rows_out,
    )


async def build_vendor_spend_summary(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    definition: ReportDefinition,
    start: date,
    end: date,
    *,
    as_of: bool = False,
) -> ReportPreview:
    currency = await _currency(db, tenant_id)
    date_clause, period_label = _register_window(start, end, as_of=as_of)
    columns = ["Vendor", "# Invoices", "Total Invoiced", "Total Paid", "Outstanding"]
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
    )
    missing_paid_amount = False
    by_vendor: dict[str, dict[str, Decimal | int | str]] = {}
    for invoice, payments in _group_invoice_payments((await db.execute(stmt)).all()):
        key, display = _vendor_group_key(invoice.vendor)
        if key not in by_vendor:
            by_vendor[key] = {
                "name": display,
                "count": 0,
                "invoiced": _ZERO,
                "paid": _ZERO,
            }
        total = Decimal(str(invoice.total or 0))
        by_vendor[key]["count"] = int(by_vendor[key]["count"]) + 1
        by_vendor[key]["invoiced"] = Decimal(str(by_vendor[key]["invoiced"])) + total
        paid_amt = _ZERO
        for payment in payments:
            if payment.status != PaymentStatus.PAID:
                continue
            added, missing = _paid_payment_amount(payment)
            if missing:
                missing_paid_amount = True
            paid_amt += added
        by_vendor[key]["paid"] = Decimal(str(by_vendor[key]["paid"])) + paid_amt
    rows_out: list[ReportPreviewRow] = []
    grand_count = 0
    grand_invoiced = _ZERO
    grand_paid = _ZERO
    for key in sorted(by_vendor, key=lambda item: str(by_vendor[item]["name"]).casefold()):
        row = by_vendor[key]
        count = int(row["count"])
        invoiced = Decimal(str(row["invoiced"]))
        paid = Decimal(str(row["paid"]))
        grand_count += count
        grand_invoiced += invoiced
        grand_paid += paid
        rows_out.append(
            _cell_row(
                str(row["name"]),
                str(count),
                _money(invoiced),
                _summary_money(paid),
                _summary_money(invoiced - paid),
            )
        )
    if rows_out:
        rows_out.append(
            _cell_row(
                "TOTAL",
                str(grand_count),
                _money(grand_invoiced),
                _summary_money(grand_paid),
                _summary_money(grand_invoiced - grand_paid),
                emphasize=True,
            )
        )
    notes = _VENDOR_SPEND_PACK_NOTES
    if missing_paid_amount:
        notes = f"{notes} {_VENDOR_SPEND_NULL_PAID_NOTES}"
    return _preview(
        definition,
        period_label=period_label,
        currency=currency,
        columns=columns,
        rows=rows_out,
        notes=notes,
    )


async def build_cash_forecast(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    definition: ReportDefinition,
    as_of: date,
) -> ReportPreview:
    currency = await _currency(db, tenant_id)
    # Posted remaining AP only. Unposted AP is excluded because
    # ensure_payment_for_invoice refuses status != PROCESSED; loosening that
    # guard reopens a Schedule/Forecast cash-need blind spot.
    remaining_by_id = {
        row.invoice_id: row.remaining
        for row in await ap_outstanding_rows(db, tenant_id, as_of)
        if row.remaining > 0
    }
    columns = ["Date", "Bucket", "Amount due", "Cumulative"]
    if not remaining_by_id:
        return _preview(
            definition,
            period_label=f"As of {as_of.isoformat()}",
            currency=currency,
            columns=columns,
            rows=[],
            notes=_CASH_FORECAST_NOTES,
        )
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
    by_date: dict[date, tuple[str, Decimal]] = {}
    for invoice, payments in _group_invoice_payments((await db.execute(stmt)).all()):
        remaining = remaining_by_id.get(invoice.id)
        if remaining is None or remaining <= 0:
            continue
        display_pay = _select_display_payment(payments)
        flow_date = None
        if display_pay is not None and display_pay.scheduled_date is not None:
            flow_date = display_pay.scheduled_date
        elif invoice.due_date is not None:
            flow_date = invoice.due_date
        if flow_date is None:
            continue
        bucket = due_bucket(invoice.due_date, as_of)
        if bucket == "Overdue":
            flow_date = as_of
        prev_bucket, prev_amt = by_date.get(flow_date, ("", _ZERO))
        label = bucket if not prev_bucket or prev_bucket == bucket else "Mixed"
        by_date[flow_date] = (label, prev_amt + remaining)
    rows_out: list[ReportPreviewRow] = []
    cumulative = _ZERO
    for day in sorted(by_date):
        bucket, amount = by_date[day]
        cumulative += amount
        rows_out.append(
            _cell_row(day.isoformat(), bucket, _money(amount), _money(cumulative))
        )
    return _preview(
        definition,
        period_label=f"As of {as_of.isoformat()}",
        currency=currency,
        columns=columns,
        rows=rows_out,
        notes=_CASH_FORECAST_NOTES,
    )
