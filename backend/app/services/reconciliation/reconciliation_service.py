from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import EntryType, JournalEntry
from app.models.journal_batch import JournalBatch, JournalBatchStatus
from app.models.reconciliation import DailyReconciliation
from app.schemas.rule_book_config import RuleBookConfigPayload
from app.services.invoice.invoice_accrual_date import effective_invoice_recon_date
from app.services.invoice.invoice_amounts import invoice_payable_total
from app.services.master_data.party_coa_subledger_service import (
    control_account_codes_for_parent,
)
from app.services.rule_book.rule_book_mapper import (
    ROUTE_SALES,
    get_payable_account_mapping,
    get_receivable_account_mapping,
    load_classification_config,
)

_TOLERANCE = Decimal("0.01")

# ---------------------------------------------------------------------------
# RC1 countable invoice policy (exact include / exclude)
#
# Invoice side and journal side MUST use the same set.
#
# INCLUDE
#   - InvoiceStatus.PROCESSED on the recon_date that are GL-posting documents
#     (commercial invoices — not PO/GRN/SO/DN / posting=No vault cards)
#   - Plus the ``current_invoice`` being reconciled right now (typically
#     RECONCILING), so its own totals/journals count before status flips to
#     PROCESSED — when that invoice itself is GL-posting
#
# EXCLUDE (never count totals or journals toward RC1/RC2)
#   - PENDING, PARSING, VALIDATING, MAPPING, JOURNALING
#   - RECONCILING when it is NOT the current_invoice (crash/orphan mid-flight)
#   - EXCEPTION, REJECTED, DUPLICATE_SKIPPED
#   - Supporting / non-posting docs (PO, GRN, SO, DN, posting=No) even when
#     PROCESSED — they have totals but no accrual journals and must not poison
#     day-level AP/AR RC1 for commercial invoices on the same date
#
# "Not completed" for RC1 = any status other than PROCESSED, except the single
# current_invoice argument passed into reconcile_daily.
# ---------------------------------------------------------------------------
RC1_COUNTABLE_STATUSES: frozenset[InvoiceStatus] = frozenset({InvoiceStatus.PROCESSED})

RC1_EXCLUDED_STATUSES: frozenset[InvoiceStatus] = frozenset(
    {
        InvoiceStatus.PENDING,
        InvoiceStatus.PARSING,
        InvoiceStatus.VALIDATING,
        InvoiceStatus.MAPPING,
        InvoiceStatus.JOURNALING,
        InvoiceStatus.RECONCILING,
        InvoiceStatus.EXCEPTION,
        InvoiceStatus.DUPLICATE_SKIPPED,
        InvoiceStatus.REJECTED,
    }
)


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


def _invoice_counts_for_rc1(
    invoice: Invoice,
    *,
    config: RuleBookConfigPayload | None,
) -> bool:
    """True when this PROCESSED/current invoice belongs in AP/AR day totals."""
    from app.services.classification.document_type_playbook_profile_service import (
        gl_posting_applicable_for_invoice,
    )

    document_types = config.document_types if config is not None else None
    return gl_posting_applicable_for_invoice(
        invoice,
        document_types=document_types,
    )


async def _sum_processed_invoice_totals(
    session: AsyncSession,
    recon_date: date,
    *,
    tenant_id: uuid.UUID | int,
    sales: bool,
    config: RuleBookConfigPayload | None = None,
    exclude_invoice_id: int | None = None,
) -> tuple[int, Decimal]:
    filters = [
        Invoice.tenant_id == tenant_id,
        Invoice.status.in_(tuple(RC1_COUNTABLE_STATUSES)),
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

    rows = list((await session.execute(select(Invoice).where(*filters))).scalars().all())
    count = 0
    inv_sum = Decimal("0")
    for inv in rows:
        if not _invoice_counts_for_rc1(inv, config=config):
            continue
        count += 1
        if sales:
            if inv.total is not None:
                inv_sum += Decimal(str(inv.total))
        else:
            payable = invoice_payable_total(inv)
            if payable is not None:
                inv_sum += payable
    return count, inv_sum


def _countable_journal_filter(
    *,
    tenant_id: uuid.UUID | int,
    current_invoice: Invoice | None,
):
    """Restrict journal sums to RC1_COUNTABLE_STATUSES (+ current_invoice).

    See module-level RC1 include/exclude policy. Incomplete invoices
    (EXCEPTION / REJECTED / mid-flight, etc.) are excluded so stranded
    accrual rows cannot fail RC1 for every other invoice on that date.
    """
    countable = select(Invoice.id).where(
        Invoice.tenant_id == tenant_id,
        Invoice.status.in_(tuple(RC1_COUNTABLE_STATUSES)),
    )
    condition = JournalEntry.invoice_id.in_(countable)
    if current_invoice is not None and current_invoice.id is not None:
        condition = or_(condition, JournalEntry.invoice_id == current_invoice.id)
    return condition


def _posted_batch_join():
    """Only journal rows whose batch is still posted (not marked reversed)."""
    return JournalEntry.batch_id == JournalBatch.id


def _live_accrual_batch_filter():
    """Primary accrual postings for RC1 AP/AR — exclude reversal batches."""
    return (
        JournalBatch.status == JournalBatchStatus.POSTED.value,
        or_(
            JournalBatch.reversal_reason.is_(None),
            JournalBatch.reversal_reason == "",
        ),
    )


def _posted_batch_filter():
    """All posted batches including reversals — for RC2 day totals."""
    return (JournalBatch.status == JournalBatchStatus.POSTED.value,)


def _include_current_invoice(
    current_invoice: Invoice | None,
    recon_date: date,
    *,
    sales: bool,
    config: RuleBookConfigPayload | None = None,
) -> Decimal:
    if current_invoice is None:
        return Decimal("0")
    if not _invoice_counts_for_rc1(current_invoice, config=config):
        return Decimal("0")
    accrual_date = effective_invoice_recon_date(current_invoice)
    if accrual_date is None or accrual_date != recon_date:
        return Decimal("0")
    if _is_sales_route(current_invoice) != sales:
        return Decimal("0")
    if sales:
        if current_invoice.total is None:
            return Decimal("0")
        return current_invoice.total
    payable_total = invoice_payable_total(current_invoice)
    if payable_total is None:
        return Decimal("0")
    return payable_total


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
        config=config,
        exclude_invoice_id=exclude_id,
    )
    sales_count, sales_sum = await _sum_processed_invoice_totals(
        session,
        recon_date,
        tenant_id=tenant_id,
        sales=True,
        config=config,
        exclude_invoice_id=exclude_id,
    )

    purchase_sum += _include_current_invoice(
        current_invoice, recon_date, sales=False, config=config
    )
    sales_sum += _include_current_invoice(
        current_invoice, recon_date, sales=True, config=config
    )

    total_invoices = purchase_count + sales_count
    if current_invoice is not None:
        accrual_date = effective_invoice_recon_date(current_invoice)
        if (
            accrual_date is not None
            and accrual_date == recon_date
            and exclude_id is not None
            and _invoice_counts_for_rc1(current_invoice, config=config)
        ):
            total_invoices += 1

    countable_journal = _countable_journal_filter(
        tenant_id=tenant_id,
        current_invoice=current_invoice,
    )

    # RC1 must count AP/AR credits posted to the control (parent) account *or*
    # any vendor/customer sub-ledger code nested under it — journals routinely
    # post to the party-specific child code (see party_coa_subledger_service),
    # and filtering on the parent code alone silently undercounts real credits,
    # producing false RC1 halts (or masking a genuine imbalance).
    payable_codes = control_account_codes_for_parent(config, payable)
    receivable_codes = control_account_codes_for_parent(config, receivable)

    ap_q = (
        select(func.coalesce(func.sum(JournalEntry.credit), 0))
        .select_from(JournalEntry)
        .join(JournalBatch, _posted_batch_join())
        .where(
            JournalEntry.tenant_id == tenant_id,
            JournalEntry.account_code.in_(payable_codes),
            JournalEntry.date == recon_date,
            JournalEntry.entry_type == EntryType.CREDIT,
            countable_journal,
            *_live_accrual_batch_filter(),
        )
    )
    ap_sum = Decimal(str((await session.execute(ap_q)).scalar() or 0))

    ar_q = (
        select(func.coalesce(func.sum(JournalEntry.debit), 0))
        .select_from(JournalEntry)
        .join(JournalBatch, _posted_batch_join())
        .where(
            JournalEntry.tenant_id == tenant_id,
            JournalEntry.account_code.in_(receivable_codes),
            JournalEntry.date == recon_date,
            JournalEntry.entry_type == EntryType.DEBIT,
            countable_journal,
            *_live_accrual_batch_filter(),
        )
    )
    ar_sum = Decimal(str((await session.execute(ar_q)).scalar() or 0))

    dr_q = (
        select(func.coalesce(func.sum(JournalEntry.debit), 0))
        .select_from(JournalEntry)
        .join(JournalBatch, _posted_batch_join())
        .where(
            JournalEntry.tenant_id == tenant_id,
            JournalEntry.date == recon_date,
            countable_journal,
            *_posted_batch_filter(),
        )
    )
    cr_q = (
        select(func.coalesce(func.sum(JournalEntry.credit), 0))
        .select_from(JournalEntry)
        .join(JournalBatch, _posted_batch_join())
        .where(
            JournalEntry.tenant_id == tenant_id,
            JournalEntry.date == recon_date,
            countable_journal,
            *_posted_batch_filter(),
        )
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
