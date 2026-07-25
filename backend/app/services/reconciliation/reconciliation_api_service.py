"""Daily reconciliation list, detail queries, and drill-down builders."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invoice import Invoice
from app.models.journal import JournalEntry
from app.models.reconciliation import DailyReconciliation
from app.schemas.reconciliation import (
    ReconciliationDayDetail,
    ReconciliationDayInvoice,
    ReconciliationJournalLine,
    ReconciliationResponse,
)
from app.services.reconciliation.reconciliation_service import (
    RC1_COUNTABLE_STATUSES,
    reconcile_daily,
)
from app.services.rule_book.rule_book_mapper import load_classification_config

_RC1_COUNTABLE = RC1_COUNTABLE_STATUSES


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


async def _enrich_response(
    db: AsyncSession,
    row: DailyReconciliation,
    *,
    tenant_id: uuid.UUID,
) -> ReconciliationResponse:
    config = await load_classification_config(db, tenant_id)
    result = await reconcile_daily(
        db, row.date, tenant_id=tenant_id, config=config
    )
    response = ReconciliationResponse.model_validate(row)
    return response.model_copy(
        update={
            "rc1_passed": result.rc1_passed,
            "rc2_passed": result.rc2_passed,
        }
    )


async def list_daily_reconciliations(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> list[ReconciliationResponse]:
    rows = (
        await db.execute(
            select(DailyReconciliation)
            .where(DailyReconciliation.tenant_id == tenant_id)
            .order_by(DailyReconciliation.date.desc())
        )
    ).scalars().all()
    return [await _enrich_response(db, row, tenant_id=tenant_id) for row in rows]


async def get_daily_reconciliation(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    recon_date: date,
) -> ReconciliationResponse | None:
    row = (
        await db.execute(
            select(DailyReconciliation).where(
                DailyReconciliation.date == recon_date,
                DailyReconciliation.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        return None
    return await _enrich_response(db, row, tenant_id=tenant_id)


async def build_reconciliation_day_detail(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    recon_date: date,
) -> ReconciliationDayDetail:
    config = await load_classification_config(db, tenant_id)
    result = await reconcile_daily(
        db, recon_date, tenant_id=tenant_id, config=config
    )

    invoices = (
        await db.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.status.in_(_RC1_COUNTABLE),
                Invoice.invoice_date == recon_date,
            )
            .order_by(Invoice.id)
        )
    ).scalars().all()

    journal_rows = (
        await db.execute(
            select(JournalEntry, Invoice.vendor)
            .join(Invoice, JournalEntry.invoice_id == Invoice.id)
            .where(
                JournalEntry.tenant_id == tenant_id,
                JournalEntry.date == recon_date,
                Invoice.status.in_(_RC1_COUNTABLE),
            )
            .order_by(JournalEntry.id)
        )
    ).all()

    journal_lines = [
        ReconciliationJournalLine(
            id=entry.id,
            invoice_id=entry.invoice_id,
            vendor=vendor,
            account_code=entry.account_code,
            account_name=entry.account_name,
            debit=_round_money(Decimal(str(entry.debit or 0))),
            credit=_round_money(Decimal(str(entry.credit or 0))),
            entry_type=entry.entry_type.value,
        )
        for entry, vendor in journal_rows
    ]

    invoices_total = _round_money(
        result.purchase_invoice_total + result.sales_invoice_total
    )
    delta_dr_cr = _round_money(result.total_debits - result.total_credits)
    delta_vs_invoices = _round_money(
        (result.purchase_invoice_total - result.total_ap_credits)
        + (result.sales_invoice_total - result.total_ar_debits)
    )

    return ReconciliationDayDetail(
        date=recon_date,
        invoices_total=invoices_total,
        total_debits=_round_money(result.total_debits),
        total_credits=_round_money(result.total_credits),
        delta_dr_cr=delta_dr_cr,
        delta_vs_invoices=delta_vs_invoices,
        rc1_passed=result.rc1_passed,
        rc2_passed=result.rc2_passed,
        is_balanced=result.is_balanced,
        halt_reason=result.halt_reason,
        journal_lines=journal_lines,
        invoices=[
            ReconciliationDayInvoice(
                id=inv.id,
                vendor=inv.vendor,
                invoice_no=inv.invoice_no,
                total=_round_money(Decimal(str(inv.total or 0))) if inv.total is not None else None,
            )
            for inv in invoices
        ],
    )
