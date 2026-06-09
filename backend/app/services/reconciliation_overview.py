"""Ledger reconciliation overview — processed invoices with journal postings."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry
from app.schemas.reconciliation import (
    ReconDayOverviewRow,
    ReconInvoiceOverviewRow,
    ReconPostingRow,
    ReconciliationOverview,
)
from app.services.currency import BASE_CURRENCY

_PROCESSED = frozenset({InvoiceStatus.PROCESSED})


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _document_ref(invoice: Invoice) -> str:
    if invoice.invoice_no and invoice.invoice_no.strip():
        return invoice.invoice_no.strip()
    return f"INV-{invoice.id:03d}"


def _postings_for_invoice(entries: list[JournalEntry]) -> list[ReconPostingRow]:
    rows: list[ReconPostingRow] = []
    for entry in sorted(entries, key=lambda e: e.id):
        account = (entry.account_name or entry.account_code or "").strip() or "—"
        rows.append(
            ReconPostingRow(
                account=account,
                debit=_round_money(Decimal(str(entry.debit or 0))),
                credit=_round_money(Decimal(str(entry.credit or 0))),
            )
        )
    return rows


async def build_reconciliation_overview(
    session: AsyncSession,
    *,
    org_id: int,
) -> ReconciliationOverview:
    stmt = (
        select(Invoice)
        .where(
            Invoice.org_id == org_id,
            Invoice.status.in_(_PROCESSED),
            Invoice.invoice_date.is_not(None),
        )
        .options(selectinload(Invoice.journal_entries))
        .order_by(Invoice.invoice_date, Invoice.id)
    )
    invoices = (await session.execute(stmt)).scalars().unique().all()

    by_date: dict[date, list[ReconInvoiceOverviewRow]] = defaultdict(list)
    sum_totals = Decimal("0")
    sum_dr = Decimal("0")
    sum_cr = Decimal("0")

    for invoice in invoices:
        if not invoice.journal_entries:
            continue
        inv_date = invoice.invoice_date
        if inv_date is None:
            continue

        postings = _postings_for_invoice(list(invoice.journal_entries))
        row_dr = _round_money(sum(p.debit for p in postings))
        row_cr = _round_money(sum(p.credit for p in postings))
        total = _round_money(Decimal(str(invoice.total or 0)))

        sum_totals += total
        sum_dr += row_dr
        sum_cr += row_cr

        by_date[inv_date].append(
            ReconInvoiceOverviewRow(
                id=_document_ref(invoice),
                invoice_id=invoice.id,
                vendor=(invoice.vendor or "—").strip() or "—",
                total=total,
                postings=postings,
            )
        )

    sum_totals = _round_money(sum_totals)
    sum_dr = _round_money(sum_dr)
    sum_cr = _round_money(sum_cr)
    delta_dr_cr = _round_money(sum_dr - sum_cr)

    day_rows: list[ReconDayOverviewRow] = []
    for inv_date in sorted(by_date.keys()):
        day_invoices = by_date[inv_date]
        day_dr = _round_money(sum(sum(p.debit for p in inv.postings) for inv in day_invoices))
        day_cr = _round_money(sum(sum(p.credit for p in inv.postings) for inv in day_invoices))
        day_rows.append(
            ReconDayOverviewRow(
                date=inv_date,
                count=len(day_invoices),
                sum_dr=day_dr,
                sum_cr=day_cr,
                delta=_round_money(day_dr - day_cr),
                invoices=day_invoices,
            )
        )

    return ReconciliationOverview(
        sum_totals=sum_totals,
        sum_dr=sum_dr,
        sum_cr=sum_cr,
        delta_dr_cr=delta_dr_cr,
        balanced=delta_dr_cr == 0,
        base_currency=BASE_CURRENCY,
        by_date=day_rows,
    )
