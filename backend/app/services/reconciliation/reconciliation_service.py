from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry
from app.models.reconciliation import DailyReconciliation
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.rule_book.rule_book_mapper import (
    ROUTE_SALES,
    get_payable_account_mapping,
    get_receivable_account_mapping,
    load_classification_config,
)

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
    purchase_invoice_total: Decimal = Decimal("0")
    sales_invoice_total: Decimal = Decimal("0")
    total_ar_debits: Decimal = Decimal("0")


def _is_sales_route(invoice: Invoice) -> bool:
    return (invoice.route_target or "").strip() == ROUTE_SALES


async def _sum_processed_invoice_totals(
    session: AsyncSession,
    recon_date: date,
    *,
    tenant_id: uuid.UUID | int,
    sales: bool,
    exclude_invoice_id: int | None = None,
) -> tuple[int, Decimal]:
    filters = [
        Invoice.tenant_id == tenant_id,
        Invoice.status == InvoiceStatus.PROCESSED,
        Invoice.invoice_date == recon_date,
    ]
    if sales:
        filters.append(Invoice.route_target == ROUTE_SALES)
    else:
        filters.append(
            or_(Invoice.route_target.is_(None), Invoice.route_target != ROUTE_SALES)
        )
    if exclude_invoice_id is not None:
        filters.append(Invoice.id != exclude_invoice_id)

    count, inv_sum = (
        await session.execute(
            select(
                func.count(Invoice.id),
                func.coalesce(func.sum(Invoice.total), 0),
            ).where(*filters)
        )
    ).one()
    return int(count or 0), Decimal(str(inv_sum or 0))


def _include_current_invoice(
    current_invoice: Invoice | None,
    recon_date: date,
    *,
    sales: bool,
) -> Decimal:
    if current_invoice is None:
        return Decimal("0")
    if current_invoice.invoice_date != recon_date or current_invoice.total is None:
        return Decimal("0")
    if _is_sales_route(current_invoice) != sales:
        return Decimal("0")
    return current_invoice.total


async def reconcile_daily(
    session: AsyncSession,
    recon_date: date,
    *,
    tenant_id: uuid.UUID | int,
    current_invoice: Invoice | None = None,
    config: RuleBookConfigPayload | None = None,
) -> ReconciliationResult:
    if config is None:
        config = await load_classification_config(session, tenant_id)

    payable = get_payable_account_mapping(config)
    receivable = get_receivable_account_mapping(config)
    exclude_id = current_invoice.id if current_invoice is not None else None

    purchase_count, purchase_sum = await _sum_processed_invoice_totals(
        session,
        recon_date,
        tenant_id=tenant_id,
        sales=False,
        exclude_invoice_id=exclude_id,
    )
    sales_count, sales_sum = await _sum_processed_invoice_totals(
        session,
        recon_date,
        tenant_id=tenant_id,
        sales=True,
        exclude_invoice_id=exclude_id,
    )

    purchase_sum += _include_current_invoice(current_invoice, recon_date, sales=False)
    sales_sum += _include_current_invoice(current_invoice, recon_date, sales=True)

    total_invoices = purchase_count + sales_count
    if current_invoice is not None and current_invoice.invoice_date == recon_date:
        if exclude_id is not None:
            total_invoices += 1

    ap_q = (
        select(func.coalesce(func.sum(JournalEntry.credit), 0))
        .select_from(JournalEntry)
        .where(
            JournalEntry.tenant_id == tenant_id,
            JournalEntry.account_code == payable.account_code,
            JournalEntry.date == recon_date,
            JournalEntry.entry_type == EntryType.CREDIT,
        )
    )
    ap_sum = Decimal(str((await session.execute(ap_q)).scalar() or 0))

    ar_q = (
        select(func.coalesce(func.sum(JournalEntry.debit), 0))
        .select_from(JournalEntry)
        .where(
            JournalEntry.tenant_id == tenant_id,
            JournalEntry.account_code == receivable.account_code,
            JournalEntry.date == recon_date,
            JournalEntry.entry_type == EntryType.DEBIT,
        )
    )
    ar_sum = Decimal(str((await session.execute(ar_q)).scalar() or 0))

    dr_q = (
        select(func.coalesce(func.sum(JournalEntry.debit), 0))
        .select_from(JournalEntry)
        .where(JournalEntry.tenant_id == tenant_id, JournalEntry.date == recon_date)
    )
    cr_q = (
        select(func.coalesce(func.sum(JournalEntry.credit), 0))
        .select_from(JournalEntry)
        .where(JournalEntry.tenant_id == tenant_id, JournalEntry.date == recon_date)
    )
    debits = Decimal(str((await session.execute(dr_q)).scalar() or 0))
    credits = Decimal(str((await session.execute(cr_q)).scalar() or 0))

    purchase_rc1 = abs(purchase_sum - ap_sum) <= _TOLERANCE
    sales_rc1 = abs(sales_sum - ar_sum) <= _TOLERANCE
    rc1 = purchase_rc1 and sales_rc1
    rc2 = abs(debits - credits) <= _TOLERANCE
    halted = False
    reason = None
    if not purchase_rc1:
        halted = True
        reason = (
            f"RC1: purchase invoice totals {purchase_sum} != "
            f"payable credits ({payable.account_code}) {ap_sum}"
        )
    elif not sales_rc1:
        halted = True
        reason = (
            f"RC1: sales invoice totals {sales_sum} != "
            f"receivable debits ({receivable.account_code}) {ar_sum}"
        )
    elif not rc2:
        halted = True
        reason = f"RC2: debits {debits} != credits {credits}"

    return ReconciliationResult(
        date=recon_date,
        total_invoices=total_invoices,
        total_ap_credits=ap_sum,
        total_debits=debits,
        total_credits=credits,
        rc1_passed=rc1,
        rc2_passed=rc2,
        is_balanced=rc1 and rc2,
        halted=halted,
        halt_reason=reason,
        purchase_invoice_total=purchase_sum,
        sales_invoice_total=sales_sum,
        total_ar_debits=ar_sum,
    )


async def save_reconciliation(
    session: AsyncSession,
    result: ReconciliationResult,
    *,
    tenant_id: uuid.UUID | int,
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
