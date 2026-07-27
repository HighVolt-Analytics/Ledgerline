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
from app.models.tenant import Tenant
from app.schemas.reconciliation import (
    ReconDayOverviewRow,
    ReconInvoiceOverviewRow,
    ReconPostingRow,
    ReconciliationOverview,
)
from app.services.dossier.document_ref_service import display_document_ref
from app.services.shared.currency import UNKNOWN_CURRENCY
from app.tenant_settings import tenant_currency

_PROCESSED = frozenset({InvoiceStatus.PROCESSED})


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _document_ref(invoice: Invoice) -> str:
    return display_document_ref(invoice)


def invoice_txn_currency(invoice: Invoice) -> str:
    """ISO transaction currency for an invoice, or UNKNOWN when blank."""
    code = (invoice.currency or "").strip().upper()
    return code or UNKNOWN_CURRENCY


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


def _add_currency_amount(
    bucket: dict[str, Decimal],
    currency: str,
    amount: Decimal,
) -> None:
    bucket[currency] = _round_money(bucket.get(currency, Decimal("0")) + amount)


def _currency_buckets_balanced(
    dr_by_currency: dict[str, Decimal],
    cr_by_currency: dict[str, Decimal],
) -> bool:
    codes = set(dr_by_currency) | set(cr_by_currency)
    if not codes:
        return True
    for code in codes:
        if _round_money(dr_by_currency.get(code, Decimal("0"))) != _round_money(
            cr_by_currency.get(code, Decimal("0"))
        ):
            return False
    return True


async def build_reconciliation_overview(
    session: AsyncSession,
    *,
    tenant_id: int,
) -> ReconciliationOverview:
    stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.status.in_(_PROCESSED),
            Invoice.invoice_date.is_not(None),
        )
        .options(selectinload(Invoice.journal_entries))
        .order_by(Invoice.invoice_date, Invoice.id)
    )
    invoices = (await session.execute(stmt)).scalars().unique().all()

    tenant = await session.get(Tenant, tenant_id)
    base = (tenant_currency(tenant) or "").strip().upper()

    by_date: dict[date, list[ReconInvoiceOverviewRow]] = defaultdict(list)
    totals_by_currency: dict[str, Decimal] = {}
    dr_by_currency: dict[str, Decimal] = {}
    cr_by_currency: dict[str, Decimal] = {}
    base_sum_totals = Decimal("0")
    base_sum_dr = Decimal("0")
    base_sum_cr = Decimal("0")

    for invoice in invoices:
        if not invoice.journal_entries:
            continue
        inv_date = invoice.invoice_date
        if inv_date is None:
            continue

        currency = invoice_txn_currency(invoice)
        postings = _postings_for_invoice(list(invoice.journal_entries))
        row_dr = _round_money(sum(p.debit for p in postings))
        row_cr = _round_money(sum(p.credit for p in postings))
        total = _round_money(Decimal(str(invoice.total or 0)))

        _add_currency_amount(totals_by_currency, currency, total)
        _add_currency_amount(dr_by_currency, currency, row_dr)
        _add_currency_amount(cr_by_currency, currency, row_cr)

        # Base-currency aggregates only — never mix foreign amounts into A$/base totals.
        if base and currency == base:
            base_sum_totals += total
            base_sum_dr += row_dr
            base_sum_cr += row_cr

        by_date[inv_date].append(
            ReconInvoiceOverviewRow(
                id=_document_ref(invoice),
                invoice_id=invoice.id,
                vendor=(invoice.vendor or "—").strip() or "—",
                total=total,
                currency="" if currency == UNKNOWN_CURRENCY else currency,
                postings=postings,
            )
        )

    base_sum_totals = _round_money(base_sum_totals)
    base_sum_dr = _round_money(base_sum_dr)
    base_sum_cr = _round_money(base_sum_cr)
    delta_dr_cr = _round_money(base_sum_dr - base_sum_cr)
    currency_codes = sorted(set(totals_by_currency) | set(dr_by_currency) | set(cr_by_currency))
    has_mixed = len(currency_codes) > 1

    day_rows: list[ReconDayOverviewRow] = []
    for inv_date in sorted(by_date.keys()):
        day_invoices = by_date[inv_date]
        day_totals: dict[str, Decimal] = {}
        day_dr: dict[str, Decimal] = {}
        day_cr: dict[str, Decimal] = {}
        for inv in day_invoices:
            code = (inv.currency or "").strip().upper() or UNKNOWN_CURRENCY
            _add_currency_amount(day_totals, code, inv.total)
            row_dr = _round_money(sum(p.debit for p in inv.postings))
            row_cr = _round_money(sum(p.credit for p in inv.postings))
            _add_currency_amount(day_dr, code, row_dr)
            _add_currency_amount(day_cr, code, row_cr)

        day_codes = sorted(set(day_totals) | set(day_dr) | set(day_cr))
        day_mixed = len(day_codes) > 1
        # Day header Dr/Cr: single-currency day keeps that currency's totals;
        # mixed days expose 0 at the scalar fields (use *_by_currency instead).
        if day_mixed:
            header_dr = Decimal("0.00")
            header_cr = Decimal("0.00")
        elif day_codes and day_codes[0] == UNKNOWN_CURRENCY:
            header_dr = Decimal("0.00")
            header_cr = Decimal("0.00")
        else:
            only = day_codes[0] if day_codes else base
            header_dr = _round_money(day_dr.get(only, Decimal("0")))
            header_cr = _round_money(day_cr.get(only, Decimal("0")))

        day_rows.append(
            ReconDayOverviewRow(
                date=inv_date,
                count=len(day_invoices),
                sum_dr=header_dr,
                sum_cr=header_cr,
                delta=_round_money(header_dr - header_cr),
                has_mixed_currencies=day_mixed,
                currencies=[c for c in day_codes if c != UNKNOWN_CURRENCY],
                totals_by_currency=day_totals,
                dr_by_currency=day_dr,
                cr_by_currency=day_cr,
                invoices=day_invoices,
            )
        )

    return ReconciliationOverview(
        sum_totals=base_sum_totals,
        sum_dr=base_sum_dr,
        sum_cr=base_sum_cr,
        delta_dr_cr=delta_dr_cr,
        balanced=_currency_buckets_balanced(dr_by_currency, cr_by_currency),
        base_currency=base,
        has_mixed_currencies=has_mixed,
        totals_by_currency=totals_by_currency,
        dr_by_currency=dr_by_currency,
        cr_by_currency=cr_by_currency,
        by_date=day_rows,
    )
