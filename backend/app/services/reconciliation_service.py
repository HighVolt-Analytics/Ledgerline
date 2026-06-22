from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry
from app.models.reconciliation import DailyReconciliation

AP_CODE = "2000"
_TOLERANCE = Decimal("0.01")


@dataclass
class ReconciliationResult:
    date: date
    total_invoices: int
    total_ap_credits: Decimal
    total_debits: Decimal
    total_credits: Decimal
    rc1_passed: bool
    rc2_passed: bool
    is_balanced: bool
    halted: bool
    halt_reason: str | None


async def reconcile_daily(
    session: AsyncSession,
    recon_date: date,
    *,
    tenant_id: int,
    current_invoice: Invoice | None = None,
) -> ReconciliationResult:
    inv_q = select(
        func.count(Invoice.id),
        func.coalesce(func.sum(Invoice.total), 0),
    ).where(
        Invoice.tenant_id == tenant_id,
        Invoice.status == InvoiceStatus.PROCESSED,
        Invoice.invoice_date == recon_date,
    )
    if current_invoice is not None:
        inv_q = inv_q.where(Invoice.id != current_invoice.id)
    count, inv_sum = (await session.execute(inv_q)).one()
    inv_sum = Decimal(str(inv_sum))

    if (
        current_invoice is not None
        and current_invoice.invoice_date == recon_date
        and current_invoice.total is not None
    ):
        count = int(count or 0) + 1
        inv_sum += current_invoice.total

    journal_org = JournalEntry.invoice_id == Invoice.id

    ap_q = (
        select(func.coalesce(func.sum(JournalEntry.credit), 0))
        .select_from(JournalEntry)
        .join(Invoice, journal_org)
        .where(
            Invoice.tenant_id == tenant_id,
            JournalEntry.account_code == AP_CODE,
            JournalEntry.date == recon_date,
            JournalEntry.entry_type == EntryType.CREDIT,
        )
    )
    ap_sum = Decimal(str((await session.execute(ap_q)).scalar() or 0))

    dr_q = (
        select(func.coalesce(func.sum(JournalEntry.debit), 0))
        .select_from(JournalEntry)
        .join(Invoice, journal_org)
        .where(Invoice.tenant_id == tenant_id, JournalEntry.date == recon_date)
    )
    cr_q = (
        select(func.coalesce(func.sum(JournalEntry.credit), 0))
        .select_from(JournalEntry)
        .join(Invoice, journal_org)
        .where(Invoice.tenant_id == tenant_id, JournalEntry.date == recon_date)
    )
    debits = Decimal(str((await session.execute(dr_q)).scalar() or 0))
    credits = Decimal(str((await session.execute(cr_q)).scalar() or 0))

    rc1 = abs(inv_sum - ap_sum) <= _TOLERANCE
    rc2 = abs(debits - credits) <= _TOLERANCE
    halted = False
    reason = None
    if not rc1:
        halted = True
        reason = f"RC1: invoice totals {inv_sum} != AP credits {ap_sum}"
    elif not rc2:
        halted = True
        reason = f"RC2: debits {debits} != credits {credits}"

    return ReconciliationResult(
        date=recon_date,
        total_invoices=int(count or 0),
        total_ap_credits=ap_sum,
        total_debits=debits,
        total_credits=credits,
        rc1_passed=rc1,
        rc2_passed=rc2,
        is_balanced=rc1 and rc2,
        halted=halted,
        halt_reason=reason,
    )


async def save_reconciliation(
    session: AsyncSession,
    result: ReconciliationResult,
    *,
    tenant_id: int,
) -> DailyReconciliation:
    stmt = select(DailyReconciliation).where(
        DailyReconciliation.date == result.date,
        DailyReconciliation.tenant_id == tenant_id,
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row:
        row.total_invoices = result.total_invoices
        row.total_ap_credits = result.total_ap_credits
        row.total_debits = result.total_debits
        row.total_credits = result.total_credits
        row.is_balanced = result.is_balanced
        row.halted = result.halted
        row.halt_reason = result.halt_reason
    else:
        row = DailyReconciliation(
            tenant_id=tenant_id,
            date=result.date,
            total_invoices=result.total_invoices,
            total_ap_credits=result.total_ap_credits,
            total_debits=result.total_debits,
            total_credits=result.total_credits,
            is_balanced=result.is_balanced,
            halted=result.halted,
            halt_reason=result.halt_reason,
        )
        session.add(row)
    await session.flush()
    return row
