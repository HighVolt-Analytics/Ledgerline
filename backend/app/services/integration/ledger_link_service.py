"""Build Ledger Link overview and export rows from live journal + payment data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.payment import Payment, PaymentStatus
from app.schemas.ledger_link import LedgerExportRowResponse, LedgerLinkExports, LedgerLinkResponse
from app.services.dossier.document_ref_service import display_document_ref
from app.services.invoice.invoice_evaluation_service import (
    ROUTE_EXPENSES,
    ROUTE_PURCHASE,
    ROUTE_TEAM,
)
from app.services.integration.publish_service import is_published_from_audit_logs
from app.services.reconciliation.reconciliation_overview import (
    build_reconciliation_overview,
    invoice_txn_currency,
)
from app.services.shared.currency import UNKNOWN_CURRENCY

_ROUTE_EXPENSES_MGMT = ROUTE_EXPENSES
_ROUTE_TEAM = ROUTE_TEAM
_ROUTE_PURCHASE = ROUTE_PURCHASE


def _export_status(logs: list[AuditLog]) -> str:
    if not is_published_from_audit_logs(logs):
        return "Pending Export"
    latest = max(
        (log for log in logs if log.event == "invoice_published_to_ledger"),
        key=lambda log: log.id,
        default=None,
    )
    if latest:
        detail = latest.detail or {}
        target = str(detail.get("target", "")).strip()
        if target:
            return f"Pushed to {target}"
    return "Exported"


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
    logs: list[AuditLog],
    *,
    doc_prefix: str,
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
        status=_export_status(logs),
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


async def build_ledger_link(
    session: AsyncSession,
    *,
    tenant_id: int,
) -> LedgerLinkResponse:
    overview = await build_reconciliation_overview(session, tenant_id=tenant_id)

    invoices = (
        await session.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.status == InvoiceStatus.PROCESSED,
            )
            .options(selectinload(Invoice.journal_entries))
            .order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
        )
    ).scalars().unique().all()

    invoice_ids = [inv.id for inv in invoices]
    audit_by_id: dict[int, list[AuditLog]] = {i: [] for i in invoice_ids}
    if invoice_ids:
        logs = (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.invoice_id.in_(invoice_ids))
                .order_by(AuditLog.created_at.desc())
            )
        ).scalars().all()
        for row in logs:
            if row.invoice_id is not None:
                audit_by_id.setdefault(row.invoice_id, []).append(row)

    exports = LedgerLinkExports()
    for invoice in invoices:
        row = _invoice_export_row(
            invoice,
            audit_by_id.get(invoice.id, []),
            doc_prefix="INV",
        )
        if row is None:
            continue
        route = (invoice.route_target or "").strip()
        if route == _ROUTE_PURCHASE:
            exports.purchases.append(row)
        elif route == _ROUTE_TEAM:
            exports.expenses.append(row)
        elif route == _ROUTE_EXPENSES_MGMT:
            exports.bills.append(row)
        else:
            exports.invoices.append(row)

    payments = (
        await session.execute(
            select(Payment)
            .where(Payment.tenant_id == tenant_id)
            .order_by(Payment.id.desc())
        )
    ).scalars().all()
    exports.payments = [_payment_export_row(payment) for payment in payments]

    return LedgerLinkResponse(overview=overview, exports=exports)
