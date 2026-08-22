"""Build Ledger Link overview and export rows from live journal + payment data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry
from app.models.payment import Payment, PaymentStatus
from app.schemas.ledger_link import (
    LedgerExportGroupMeta,
    LedgerExportRowResponse,
    LedgerLinkExports,
    LedgerLinkResponse,
)
from app.services.dossier.document_ref_service import display_document_ref
from app.services.invoice.invoice_evaluation_service import (
    ROUTE_EXPENSES,
    ROUTE_PURCHASE,
    ROUTE_TEAM,
)
from app.services.integration.publish_service import published_invoice_ids
from app.services.reconciliation.reconciliation_overview import (
    build_reconciliation_overview,
    invoice_txn_currency,
)
from app.services.shared.currency import UNKNOWN_CURRENCY

_ROUTE_EXPENSES_MGMT = ROUTE_EXPENSES
_ROUTE_TEAM = ROUTE_TEAM
_ROUTE_PURCHASE = ROUTE_PURCHASE
_EXPORT_GROUP_LIMIT = 50
_OVERVIEW_MAX_DAYS = 90
_SPECIAL_ROUTES = frozenset({_ROUTE_PURCHASE, _ROUTE_TEAM, _ROUTE_EXPENSES_MGMT})


async def _export_statuses(
    session: AsyncSession,
    tenant_id,
    invoice_ids: list[int],
) -> dict[int, str]:
    if not invoice_ids:
        return {}
    published = await published_invoice_ids(session, invoice_ids, tenant_id=tenant_id)
    targets: dict[int, str] = {}
    if published:
        latest_ids = (
            await session.execute(
                select(AuditLog.invoice_id, func.max(AuditLog.id)).where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.invoice_id.in_(list(published)),
                    AuditLog.event == "invoice_published_to_ledger",
                ).group_by(AuditLog.invoice_id)
            )
        ).all()
        log_ids = [row[1] for row in latest_ids if row[1]]
        if log_ids:
            logs = (
                await session.execute(select(AuditLog).where(AuditLog.id.in_(log_ids)))
            ).scalars().all()
            for log in logs:
                if log.invoice_id is None:
                    continue
                target = str((log.detail or {}).get("target", "")).strip()
                if target:
                    targets[log.invoice_id] = target
    out: dict[int, str] = {}
    for invoice_id in invoice_ids:
        if invoice_id not in published:
            out[invoice_id] = "Pending Export"
        elif invoice_id in targets:
            out[invoice_id] = f"Pushed to {targets[invoice_id]}"
        else:
            out[invoice_id] = "Exported"
    return out


def _primary_debit_credit(postings: list[tuple[str, Decimal, Decimal]]) -> tuple[str, str]:
    debit_acct = "—"
    credit_acct = "—"
    for account, debit, credit in postings:
        if debit > 0 and debit_acct == "—":
            debit_acct = account
        if credit > 0 and credit_acct == "—":
            credit_acct = account
    return debit_acct, credit_acct


def _invoice_export_row(
    invoice: Invoice,
    status: str,
) -> LedgerExportRowResponse | None:
    if not invoice.journal_entries:
        return None
    postings: list[tuple[str, Decimal, Decimal]] = []
    for entry in sorted(invoice.journal_entries, key=lambda row: row.id):
        account = (entry.account_name or entry.account_code or "—").strip() or "—"
        postings.append(
            (
                account,
                Decimal(str(entry.debit or 0)),
                Decimal(str(entry.credit or 0)),
            )
        )
    debit, credit = _primary_debit_credit(postings)
    inv_date = invoice.invoice_date
    date_str = inv_date.isoformat() if isinstance(inv_date, date) else "—"
    doc = (invoice.invoice_no or "").strip() or display_document_ref(invoice)
    amount = float(invoice.total or 0)
    currency = invoice_txn_currency(invoice)
    return LedgerExportRowResponse(
        id=f"ll-inv-{invoice.id}",
        doc=doc,
        date=date_str,
        party=(invoice.vendor or "—").strip() or "—",
        debit=debit,
        credit=credit,
        amount=round(amount, 2),
        status=status,
        currency="" if currency == UNKNOWN_CURRENCY else currency,
    )


def _payment_export_row(payment: Payment) -> LedgerExportRowResponse:
    paid = payment.status == PaymentStatus.PAID
    status = "Exported" if paid else "Pending Export"
    if payment.status == PaymentStatus.SCHEDULED:
        status = "Ready"
    date_str = (
        payment.paid_date.date().isoformat()
        if payment.paid_date
        else payment.scheduled_date.isoformat()
        if payment.scheduled_date
        else payment.due_date.isoformat()
        if payment.due_date
        else "—"
    )
    currency = (payment.currency or "").strip().upper()
    return LedgerExportRowResponse(
        id=f"ll-pay-{payment.id}",
        doc=f"PAY-{payment.id:04d}",
        date=date_str,
        party=(payment.vendor or "—").strip() or "—",
        debit="Accounts Payable",
        credit="Bank",
        amount=round(float(payment.amount), 2),
        status=status,
        currency=currency,
    )


def _route_bucket(route: str) -> str:
    if route == _ROUTE_PURCHASE:
        return "purchases"
    if route == _ROUTE_TEAM:
        return "expenses"
    if route == _ROUTE_EXPENSES_MGMT:
        return "bills"
    return "invoices"


def _empty_overview():
    from app.schemas.reconciliation import ReconciliationOverview

    return ReconciliationOverview(
        sum_totals=0,
        sum_dr=0,
        sum_cr=0,
        delta_dr_cr=0,
        balanced=True,
        by_date=[],
    )


async def _invoice_export_group_meta(
    session: AsyncSession,
    tenant_id,
) -> dict[str, LedgerExportGroupMeta]:
    has_journals = exists(select(JournalEntry.id).where(JournalEntry.invoice_id == Invoice.id))
    rows = (
        await session.execute(
            select(
                Invoice.route_target,
                Invoice.currency,
                func.count(Invoice.id),
                func.coalesce(func.sum(Invoice.total), 0),
            )
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.status == InvoiceStatus.PROCESSED,
                has_journals,
            )
            .group_by(Invoice.route_target, Invoice.currency)
        )
    ).all()
    meta: dict[str, LedgerExportGroupMeta] = {
        "invoices": LedgerExportGroupMeta(),
        "bills": LedgerExportGroupMeta(),
        "expenses": LedgerExportGroupMeta(),
        "purchases": LedgerExportGroupMeta(),
        "payments": LedgerExportGroupMeta(),
    }
    for route, currency, count, amount in rows:
        bucket = _route_bucket((route or "").strip())
        item = meta[bucket]
        item.count += int(count or 0)
        code = (currency or "").strip().upper() or UNKNOWN_CURRENCY
        item.totals_by_currency[code] = item.totals_by_currency.get(code, 0.0) + float(amount or 0)
    return meta


async def _payment_export_group_meta(
    session: AsyncSession,
    tenant_id,
) -> LedgerExportGroupMeta:
    rows = (
        await session.execute(
            select(
                Payment.currency,
                func.count(Payment.id),
                func.coalesce(func.sum(Payment.amount), 0),
            )
            .where(Payment.tenant_id == tenant_id)
            .group_by(Payment.currency)
        )
    ).all()
    meta = LedgerExportGroupMeta()
    for currency, count, amount in rows:
        meta.count += int(count or 0)
        code = (currency or "").strip().upper() or UNKNOWN_CURRENCY
        meta.totals_by_currency[code] = meta.totals_by_currency.get(code, 0.0) + float(amount or 0)
    return meta


async def _load_export_invoices(
    session: AsyncSession,
    tenant_id,
    *,
    limit: int | None,
) -> list[Invoice]:
    has_journals = exists(select(JournalEntry.id).where(JournalEntry.invoice_id == Invoice.id))
    if limit is None:
        return (
            await session.execute(
                select(Invoice)
                .where(
                    Invoice.tenant_id == tenant_id,
                    Invoice.status == InvoiceStatus.PROCESSED,
                    has_journals,
                )
                .options(selectinload(Invoice.journal_entries))
                .order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
            )
        ).scalars().unique().all()

    buckets = [
        Invoice.route_target == _ROUTE_PURCHASE,
        Invoice.route_target == _ROUTE_TEAM,
        Invoice.route_target == _ROUTE_EXPENSES_MGMT,
        or_(
            Invoice.route_target.is_(None),
            Invoice.route_target.notin_(_SPECIAL_ROUTES),
        ),
    ]
    loaded: list[Invoice] = []
    seen: set[int] = set()
    for bucket in buckets:
        rows = (
            await session.execute(
                select(Invoice)
                .where(
                    Invoice.tenant_id == tenant_id,
                    Invoice.status == InvoiceStatus.PROCESSED,
                    has_journals,
                    bucket,
                )
                .options(selectinload(Invoice.journal_entries))
                .order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
                .limit(limit)
            )
        ).scalars().unique().all()
        for invoice in rows:
            if invoice.id in seen:
                continue
            seen.add(invoice.id)
            loaded.append(invoice)
    return loaded


async def build_ledger_link_exports(
    session: AsyncSession,
    *,
    tenant_id,
    limit: int | None = None,
) -> LedgerLinkExports:
    invoices = await _load_export_invoices(session, tenant_id, limit=limit)
    statuses = await _export_statuses(session, tenant_id, [inv.id for inv in invoices])
    group_meta = await _invoice_export_group_meta(session, tenant_id)
    group_meta["payments"] = await _payment_export_group_meta(session, tenant_id)

    exports = LedgerLinkExports(group_meta=group_meta)
    for invoice in invoices:
        row = _invoice_export_row(invoice, statuses.get(invoice.id, "Pending Export"))
        if row is None:
            continue
        bucket = _route_bucket((invoice.route_target or "").strip())
        getattr(exports, bucket).append(row)

    pay_stmt = (
        select(Payment)
        .where(Payment.tenant_id == tenant_id)
        .order_by(Payment.id.desc())
    )
    if limit is not None:
        pay_stmt = pay_stmt.limit(limit)
    payments = (await session.execute(pay_stmt)).scalars().all()
    exports.payments = [_payment_export_row(payment) for payment in payments]
    return exports


async def build_ledger_link(
    session: AsyncSession,
    *,
    tenant_id,
    fields: str | None = None,
) -> LedgerLinkResponse:
    include_overview = fields in (None, "", "overview")
    include_exports = fields in (None, "", "exports")
    overview = (
        await build_reconciliation_overview(
            session,
            tenant_id=tenant_id,
            include_day_invoices=fields is None or fields == "",
            max_days=_OVERVIEW_MAX_DAYS if fields == "overview" else None,
        )
        if include_overview
        else _empty_overview()
    )
    exports = (
        await build_ledger_link_exports(
            session,
            tenant_id=tenant_id,
            limit=_EXPORT_GROUP_LIMIT if fields == "exports" else None,
        )
        if include_exports
        else LedgerLinkExports()
    )
    return LedgerLinkResponse(overview=overview, exports=exports)
