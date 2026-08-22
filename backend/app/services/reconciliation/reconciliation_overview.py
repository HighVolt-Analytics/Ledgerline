"""Ledger reconciliation overview — processed invoices with journal postings."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
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


def _day_header_row(
    inv_date: date,
    items: list[tuple[str, Decimal, Decimal, Decimal, ReconInvoiceOverviewRow | None]],
    *,
    base: str,
    include_invoices: bool,
) -> ReconDayOverviewRow:
    day_totals: dict[str, Decimal] = {}
    day_dr: dict[str, Decimal] = {}
    day_cr: dict[str, Decimal] = {}
    invoices: list[ReconInvoiceOverviewRow] = []
    for currency, total, row_dr, row_cr, invoice_row in items:
        _add_currency_amount(day_totals, currency, total)
        _add_currency_amount(day_dr, currency, row_dr)
        _add_currency_amount(day_cr, currency, row_cr)
        if include_invoices and invoice_row is not None:
            invoices.append(invoice_row)

    day_codes = sorted(set(day_totals) | set(day_dr) | set(day_cr))
    day_mixed = len(day_codes) > 1
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

    return ReconDayOverviewRow(
        date=inv_date,
        count=len(items),
        sum_dr=header_dr,
        sum_cr=header_cr,
        delta=_round_money(header_dr - header_cr),
        has_mixed_currencies=day_mixed,
        currencies=[c for c in day_codes if c != UNKNOWN_CURRENCY],
        totals_by_currency=day_totals,
        dr_by_currency=day_dr,
        cr_by_currency=day_cr,
        invoices=invoices,
    )


def _assemble_overview(
    items_by_date: dict[date, list[tuple[str, Decimal, Decimal, Decimal, ReconInvoiceOverviewRow | None]]],
    *,
    base: str,
    include_day_invoices: bool,
    max_days: int | None,
) -> ReconciliationOverview:
    totals_by_currency: dict[str, Decimal] = {}
    dr_by_currency: dict[str, Decimal] = {}
    cr_by_currency: dict[str, Decimal] = {}
    base_sum_totals = Decimal("0")
    base_sum_dr = Decimal("0")
    base_sum_cr = Decimal("0")
    document_count = 0

    for items in items_by_date.values():
        for currency, total, row_dr, row_cr, _invoice_row in items:
            document_count += 1
            _add_currency_amount(totals_by_currency, currency, total)
            _add_currency_amount(dr_by_currency, currency, row_dr)
            _add_currency_amount(cr_by_currency, currency, row_cr)
            if base and currency == base:
                base_sum_totals += total
                base_sum_dr += row_dr
                base_sum_cr += row_cr

    base_sum_totals = _round_money(base_sum_totals)
    base_sum_dr = _round_money(base_sum_dr)
    base_sum_cr = _round_money(base_sum_cr)
    delta_dr_cr = _round_money(base_sum_dr - base_sum_cr)
    currency_codes = sorted(set(totals_by_currency) | set(dr_by_currency) | set(cr_by_currency))
    has_mixed = len(currency_codes) > 1

    dates = sorted(items_by_date.keys())
    total_day_count = len(dates)
    if max_days is not None and total_day_count > max_days:
        dates = dates[-max_days:]

    day_rows = [
        _day_header_row(
            inv_date,
            items_by_date[inv_date],
            base=base,
            include_invoices=include_day_invoices,
        )
        for inv_date in dates
    ]

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
        document_count=document_count,
        total_day_count=total_day_count,
    )


async def build_reconciliation_overview(
    session: AsyncSession,
    *,
    tenant_id: int,
    include_day_invoices: bool = True,
    max_days: int | None = None,
) -> ReconciliationOverview:
    tenant = await session.get(Tenant, tenant_id)
    base = (tenant_currency(tenant) or "").strip().upper()
    items_by_date: dict[date, list[tuple[str, Decimal, Decimal, Decimal, ReconInvoiceOverviewRow | None]]] = defaultdict(list)

    if include_day_invoices:
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
            items_by_date[inv_date].append(
                (
                    currency,
                    total,
                    row_dr,
                    row_cr,
                    ReconInvoiceOverviewRow(
                        id=_document_ref(invoice),
                        invoice_id=invoice.id,
                        vendor=(invoice.vendor or "—").strip() or "—",
                        total=total,
                        currency="" if currency == UNKNOWN_CURRENCY else currency,
                        postings=postings,
                    ),
                )
            )
    else:
        rows = (
            await session.execute(
                select(
                    Invoice.invoice_date,
                    Invoice.currency,
                    Invoice.total,
                    func.coalesce(func.sum(JournalEntry.debit), 0),
                    func.coalesce(func.sum(JournalEntry.credit), 0),
                )
                .join(JournalEntry, JournalEntry.invoice_id == Invoice.id)
                .where(
                    Invoice.tenant_id == tenant_id,
                    Invoice.status.in_(_PROCESSED),
                    Invoice.invoice_date.is_not(None),
                )
                .group_by(Invoice.id, Invoice.invoice_date, Invoice.currency, Invoice.total)
            )
        ).all()
        for inv_date, currency_raw, total_raw, row_dr_raw, row_cr_raw in rows:
            if inv_date is None:
                continue
            currency = (currency_raw or "").strip().upper() or UNKNOWN_CURRENCY
            total = _round_money(Decimal(str(total_raw or 0)))
            row_dr = _round_money(Decimal(str(row_dr_raw or 0)))
            row_cr = _round_money(Decimal(str(row_cr_raw or 0)))
            items_by_date[inv_date].append((currency, total, row_dr, row_cr, None))

    return _assemble_overview(
        items_by_date,
        base=base,
        include_day_invoices=include_day_invoices,
        max_days=max_days,
    )


async def build_reconciliation_day_overview(
    session: AsyncSession,
    *,
    tenant_id: int,
    day: date,
) -> ReconDayOverviewRow:
    tenant = await session.get(Tenant, tenant_id)
    base = (tenant_currency(tenant) or "").strip().upper()
    stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.status.in_(_PROCESSED),
            Invoice.invoice_date == day,
        )
        .options(selectinload(Invoice.journal_entries))
        .order_by(Invoice.id)
    )
    invoices = (await session.execute(stmt)).scalars().unique().all()
    items: list[tuple[str, Decimal, Decimal, Decimal, ReconInvoiceOverviewRow | None]] = []
    for invoice in invoices:
        if not invoice.journal_entries:
            continue
        currency = invoice_txn_currency(invoice)
        postings = _postings_for_invoice(list(invoice.journal_entries))
        row_dr = _round_money(sum(p.debit for p in postings))
        row_cr = _round_money(sum(p.credit for p in postings))
        total = _round_money(Decimal(str(invoice.total or 0)))
        items.append(
            (
                currency,
                total,
                row_dr,
                row_cr,
                ReconInvoiceOverviewRow(
                    id=_document_ref(invoice),
                    invoice_id=invoice.id,
                    vendor=(invoice.vendor or "—").strip() or "—",
                    total=total,
                    currency="" if currency == UNKNOWN_CURRENCY else currency,
                    postings=postings,
                ),
            )
        )
    return _day_header_row(day, items, base=base, include_invoices=True)
