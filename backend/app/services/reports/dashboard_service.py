"""Dashboard aggregates — single source of truth for KPIs and charts."""

import asyncio
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.audit import AuditLog
from app.models.tenant import Tenant
from app.models.connected_mailbox import ConnectedMailbox
from app.models.invoice import Invoice, InvoiceStatus
from app.models.user import User
from app.services.dossier.document_ref_service import dossier_public_id
from app.services.ingest.graph_client import is_graph_enabled
from app.models.journal import JournalEntry
from app.services.shared.currency import BASE_CURRENCY, convert_to_base, sum_amounts_by_currency
from app.tenant_settings import tenant_labor_rate_per_hour, tenant_timezone
from app.services.invoice.invoice_evaluation_service import (
    EVAL_AWAITING_CLASSIFICATION,
    EVAL_NEEDS_REVIEW,
    EVAL_PENDING_VENDOR,
    EVAL_UNMATCHED_EXPENSE_VENDOR,
    ROUTE_EXPENSES,
    ROUTE_PURCHASE,
    ROUTE_SALES,
    ROUTE_TEAM,
)
from app.services.sales.so_reference import resolve_so_reference_from_invoice
from app.services.payments.payment_service import payments_queue_count as _payments_table_count
from app.schemas.dashboard import (
    ActivityItem,
    AnomalyRow,
    CashForecastBucket,
    DashboardOverview,
    DashboardStats,
    KpiSparklines,
    KpiTrend,
    MailboxBreakdownRow,
    NavBadges,
    TopVendorRow,
)
from app.services.reports.dashboard_panels_service import build_dashboard_panels
from app.schemas.invoice import InvoiceStatus as InvoiceStatusSchema
from app.tenant_settings import tenant_currency, tenant_today

_APPROVAL_STATUSES = frozenset(
    {
        InvoiceStatus.EXCEPTION,
        InvoiceStatus.DUPLICATE_SKIPPED,
        InvoiceStatus.REJECTED,
    }
)
_INBOX_STATUSES = frozenset(
    {
        InvoiceStatus.PENDING,
        InvoiceStatus.PARSING,
        InvoiceStatus.VALIDATING,
        InvoiceStatus.MAPPING,
        InvoiceStatus.JOURNALING,
        InvoiceStatus.RECONCILING,
    }
)
_TEAM_EXPENSE_ACTIONABLE = _INBOX_STATUSES | frozenset({InvoiceStatus.EXCEPTION})
_TERMINAL_ANOMALY_STATUSES = frozenset(
    {
        InvoiceStatus.PROCESSED,
        InvoiceStatus.REJECTED,
        InvoiceStatus.DUPLICATE_SKIPPED,
    }
)
# Booked spend — only processed invoices contribute to value KPIs.
_BOOKED_STATUSES = frozenset({InvoiceStatus.PROCESSED})
# Terminal states excluded from sync-rate denominator.
_SYNC_EXCLUDED_STATUSES = frozenset(
    {InvoiceStatus.DUPLICATE_SKIPPED, InvoiceStatus.REJECTED}
)
_FORECAST_BUCKETS = (
    ("Overdue", -9999, -1),
    ("7 days", 0, 7),
    ("14 days", 8, 14),
    ("30 days", 15, 30),
    ("60 days", 31, 60),
    ("60+ days", 61, None),
)


def _is_email_sourced(
    email_sender: str | None,
    email_message_id: str | None,
    connected_mailbox_id: int | None,
) -> bool:
    if email_sender and str(email_sender).strip():
        return True
    if email_message_id and str(email_message_id).strip():
        return True
    return connected_mailbox_id is not None


def _month_start(today: date) -> date:
    return today.replace(day=1)


def _month_end(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1) - timedelta(days=1)
    return date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)


def parse_period(month: str | None, *, today: date | None = None) -> tuple[date, date, str]:
    """Return (month_start, month_end, period_key YYYY-MM)."""
    if month:
        parts = month.split("-")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            y, m = int(parts[0]), int(parts[1])
            if 1 <= m <= 12:
                start = date(y, m, 1)
                return start, _month_end(start), f"{y:04d}-{m:02d}"
    anchor = today or date.today()
    start = _month_start(anchor)
    return start, _month_end(start), f"{anchor.year:04d}-{anchor.month:02d}"


async def _institution_today(db: AsyncSession, tenant_id) -> date:
    tenant = await db.get(Tenant, tenant_id)
    return tenant_today(tenant)


def _invoice_date_filters(month_start: date, month_end: date):
    start = datetime.combine(month_start, time.min, tzinfo=timezone.utc)
    end = datetime.combine(month_end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return Invoice.created_at >= start, Invoice.created_at < end


async def _count_by_status(
    db: AsyncSession, status: InvoiceStatus, *, tenant_id: int
) -> int:
    q = select(func.count(Invoice.id)).where(
        Invoice.tenant_id == tenant_id,
        Invoice.status == status,
    )
    return (await db.execute(q)).scalar() or 0


async def _count_statuses(
    db: AsyncSession, statuses: frozenset[InvoiceStatus], *, tenant_id: int
) -> int:
    q = select(func.count(Invoice.id)).where(
        Invoice.tenant_id == tenant_id,
        Invoice.status.in_(statuses),
    )
    return (await db.execute(q)).scalar() or 0


async def _mailboxes_mapped(db: AsyncSession, tenant_id: int) -> int:
    return (
        await db.execute(
            select(func.count(ConnectedMailbox.id)).where(
                ConnectedMailbox.tenant_id == tenant_id,
                ConnectedMailbox.is_active.is_(True),
            )
        )
    ).scalar() or 0


async def _active_users(db: AsyncSession, tenant_id: int) -> int:
    return (
        await db.execute(
            select(func.count(User.id)).where(User.tenant_id == tenant_id)
        )
    ).scalar() or 0


def _email_source_filter():
    return (
        (Invoice.email_sender.isnot(None) & (Invoice.email_sender != ""))
        | Invoice.email_message_id.isnot(None)
        | Invoice.connected_mailbox_id.isnot(None)
    )


async def _docs_via_email(
    db: AsyncSession,
    tenant_id: int,
    *,
    month_start: date | None = None,
    month_end: date | None = None,
) -> int:
    stmt = select(func.count(Invoice.id)).where(
        Invoice.tenant_id == tenant_id,
        _email_source_filter(),
    )
    if month_start is not None and month_end is not None:
        lo, hi = _invoice_date_filters(month_start, month_end)
        stmt = stmt.where(lo, hi)
    return (await db.execute(stmt)).scalar() or 0


async def _docs_via_upload(
    db: AsyncSession,
    tenant_id: int,
    *,
    month_start: date | None = None,
    month_end: date | None = None,
) -> int:
    stmt = select(func.count(Invoice.id)).where(
        Invoice.tenant_id == tenant_id,
        ~_email_source_filter(),
    )
    if month_start is not None and month_end is not None:
        lo, hi = _invoice_date_filters(month_start, month_end)
        stmt = stmt.where(lo, hi)
    return (await db.execute(stmt)).scalar() or 0


async def _team_expenses_queue_count(db: AsyncSession, tenant_id: int) -> int:
    return (
        await db.execute(
            select(func.count(Invoice.id)).where(
                Invoice.tenant_id == tenant_id,
                Invoice.route_target == ROUTE_TEAM,
                Invoice.status.in_(_TEAM_EXPENSE_ACTIONABLE),
            )
        )
    ).scalar() or 0


async def _business_expenses_queue_count(db: AsyncSession, tenant_id: int) -> int:
    return (
        await db.execute(
            select(func.count(Invoice.id)).where(
                Invoice.tenant_id == tenant_id,
                Invoice.route_target == ROUTE_EXPENSES,
                Invoice.status.in_(_TEAM_EXPENSE_ACTIONABLE),
            )
        )
    ).scalar() or 0


async def _sales_queue_count(db: AsyncSession, tenant_id: int) -> int:
    return (
        await db.execute(
            select(func.count(Invoice.id)).where(
                Invoice.tenant_id == tenant_id,
                Invoice.route_target == ROUTE_SALES,
                Invoice.status.in_(_TEAM_EXPENSE_ACTIONABLE),
            )
        )
    ).scalar() or 0


async def _collections_queue_count(db: AsyncSession, tenant_id: int) -> int:
    from app.services.integration.collection_service import collections_queue_count

    return await collections_queue_count(db, tenant_id)


async def _payments_queue_count(db: AsyncSession, tenant_id: int) -> int:
    """Open payment workflow rows (queue, awaiting, scheduled)."""
    count = await _payments_table_count(db, tenant_id)
    if count > 0:
        return count
    return (
        await db.execute(
            select(func.count(Invoice.id)).where(
                Invoice.tenant_id == tenant_id,
                Invoice.status == InvoiceStatus.PROCESSED,
                Invoice.due_date.isnot(None),
                Invoice.total.isnot(None),
            )
        )
    ).scalar() or 0


async def _integrations_connected(db: AsyncSession, tenant_id: int) -> int:
    s = get_settings()
    count = sum(1 for flag in (s.blob_enabled, s.azure_di_enabled) if flag)
    mb_count = (
        await db.execute(
            select(func.count(ConnectedMailbox.id)).where(
                ConnectedMailbox.tenant_id == tenant_id,
                ConnectedMailbox.is_active.is_(True),
            )
        )
    ).scalar() or 0
    if mb_count and is_graph_enabled():
        count += 1
    return count


async def _count_in_period(
    db: AsyncSession,
    tenant_id: int,
    month_start: date,
    month_end: date,
    *,
    extra=None,
) -> int:
    lo, hi = _invoice_date_filters(month_start, month_end)
    stmt = select(func.count(Invoice.id)).where(
        Invoice.tenant_id == tenant_id,
        lo,
        hi,
    )
    if extra is not None:
        stmt = stmt.where(extra)
    return (await db.execute(stmt)).scalar() or 0


async def _invoice_amount_rows_in_period(
    db: AsyncSession,
    tenant_id: int,
    month_start: date,
    month_end: date,
    *,
    statuses: frozenset[InvoiceStatus] | None = None,
) -> list[tuple[str | None, Decimal | None]]:
    lo, hi = _invoice_date_filters(month_start, month_end)
    stmt = select(Invoice.currency, Invoice.total).where(
        Invoice.tenant_id == tenant_id,
        lo,
        hi,
        Invoice.total.isnot(None),
    )
    if statuses is not None:
        stmt = stmt.where(Invoice.status.in_(statuses))
    rows = (await db.execute(stmt)).all()
    return [(currency, total) for currency, total in rows]


async def _sum_value_in_period(
    db: AsyncSession,
    tenant_id: int,
    month_start: date,
    month_end: date,
    *,
    base: str | None = None,
) -> tuple[Decimal, dict[str, Decimal]]:
    rows = await _invoice_amount_rows_in_period(
        db, tenant_id, month_start, month_end, statuses=_BOOKED_STATUSES
    )
    return sum_amounts_by_currency(rows, base=base)


async def _active_users_as_of(db: AsyncSession, tenant_id: int, as_of: date) -> int:
    return (
        await db.execute(
            select(func.count(User.id)).where(
                User.tenant_id == tenant_id,
                func.date(User.created_at) <= as_of,
            )
        )
    ).scalar() or 0


async def _mailboxes_with_docs_in_period(
    db: AsyncSession,
    tenant_id: int,
    month_start: date,
    month_end: date,
) -> int:
    lo, hi = _invoice_date_filters(month_start, month_end)
    return (
        await db.execute(
            select(func.count(func.distinct(Invoice.connected_mailbox_id))).where(
                Invoice.tenant_id == tenant_id,
                Invoice.connected_mailbox_id.isnot(None),
                lo,
                hi,
            )
        )
    ).scalar() or 0


_RECON_TOLERANCE = Decimal("0.01")


async def _reconciliation_for_tenant(
    db: AsyncSession,
    tenant_id: int,
) -> tuple[bool | None, Decimal | None]:
    """Latest journal date for org invoices — balanced if debits ≈ credits."""
    latest = (
        await db.execute(
            select(func.max(JournalEntry.date))
            .join(Invoice, Invoice.id == JournalEntry.invoice_id)
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.status.in_(_BOOKED_STATUSES),
            )
        )
    ).scalar()
    if latest is None:
        return None, None

    booked = Invoice.status.in_(_BOOKED_STATUSES)
    debits = Decimal(
        str(
            (
                await db.execute(
                    select(func.coalesce(func.sum(JournalEntry.debit), 0))
                    .join(Invoice, Invoice.id == JournalEntry.invoice_id)
                    .where(Invoice.tenant_id == tenant_id, JournalEntry.date == latest, booked)
                )
            ).scalar()
            or 0
        )
    )
    credits = Decimal(
        str(
            (
                await db.execute(
                    select(func.coalesce(func.sum(JournalEntry.credit), 0))
                    .join(Invoice, Invoice.id == JournalEntry.invoice_id)
                    .where(Invoice.tenant_id == tenant_id, JournalEntry.date == latest, booked)
                )
            ).scalar()
            or 0
        )
    )
    delta = debits - credits
    return abs(delta) <= _RECON_TOLERANCE, delta


async def _distinct_vendors_in_period(
    db: AsyncSession,
    tenant_id: int,
    month_start: date,
    month_end: date,
    *,
    statuses: frozenset[InvoiceStatus] | None = None,
) -> int:
    vendor_expr = func.coalesce(Invoice.vendor, "Unknown")
    lo, hi = _invoice_date_filters(month_start, month_end)
    stmt = select(func.count(func.distinct(vendor_expr))).where(
        Invoice.tenant_id == tenant_id,
        lo,
        hi,
    )
    if statuses is not None:
        stmt = stmt.where(Invoice.status.in_(statuses))
    return (await db.execute(stmt)).scalar() or 0


async def _invoice_status_counts(
    db: AsyncSession, tenant_id: int
) -> dict[InvoiceStatus, int]:
    """Single grouped query for all status counters."""
    rows = (
        await db.execute(
            select(Invoice.status, func.count(Invoice.id))
            .where(Invoice.tenant_id == tenant_id)
            .group_by(Invoice.status)
        )
    ).all()
    return {status: int(count) for status, count in rows}


async def _period_invoice_metrics(
    db: AsyncSession,
    tenant_id: int,
    month_start: date,
    month_end: date,
) -> tuple[int, int, int]:
    """Period count, distinct vendors, and email-sourced docs in one query."""
    lo, hi = _invoice_date_filters(month_start, month_end)
    vendor_expr = func.coalesce(Invoice.vendor, "Unknown")
    row = (
        await db.execute(
            select(
                func.count(Invoice.id),
                func.count(func.distinct(vendor_expr)),
                func.coalesce(
                    func.sum(
                        case(
                            (_email_source_filter(), 1),
                            else_=0,
                        )
                    ),
                    0,
                ),
            ).where(Invoice.tenant_id == tenant_id, lo, hi)
        )
    ).one()
    return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)


def _integrations_count(mailboxes_active: int) -> int:
    s = get_settings()
    count = sum(
        1
        for flag in (
            s.blob_enabled,
            s.azure_di_enabled,
            s.azure_foundry_vision_available,
            s.claude_vision_available,
            s.gemini_vision_available,
        )
        if flag
    )
    if mailboxes_active and is_graph_enabled():
        count += 1
    return count


async def _pending_classification_count(db: AsyncSession, tenant_id: int) -> int:
    row = await db.execute(
        select(func.count())
        .select_from(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.status == InvoiceStatus.EXCEPTION,
            Invoice.evaluation_status == EVAL_AWAITING_CLASSIFICATION,
        )
    )
    return int(row.scalar() or 0)


async def build_nav_badges(db: AsyncSession, *, tenant_id: int) -> NavBadges:
    """Sidebar badge counts — status aggregate plus parallel queue counters."""
    status_counts = await _invoice_status_counts(db, tenant_id)
    pending_approval = sum(
        status_counts.get(s, 0) for s in _APPROVAL_STATUSES
    )
    inbox_count = sum(status_counts.get(s, 0) for s in _INBOX_STATUSES)
    (
        team_expenses_count,
        business_expenses_count,
        sales_count,
        payments_queue_count,
        collections_queue_count,
        mailboxes_mapped,
        pending_classification,
    ) = await asyncio.gather(
        _team_expenses_queue_count(db, tenant_id),
        _business_expenses_queue_count(db, tenant_id),
        _sales_queue_count(db, tenant_id),
        _payments_queue_count(db, tenant_id),
        _collections_queue_count(db, tenant_id),
        _mailboxes_mapped(db, tenant_id=tenant_id),
        _pending_classification_count(db, tenant_id),
    )
    return NavBadges(
        inbox_count=inbox_count,
        pending_approval=pending_approval,
        pending_classification=pending_classification,
        team_expenses_count=team_expenses_count,
        business_expenses_count=business_expenses_count,
        sales_count=sales_count,
        payments_queue_count=payments_queue_count,
        collections_queue_count=collections_queue_count,
        integrations_connected=_integrations_count(mailboxes_mapped),
    )


async def build_stats(
    db: AsyncSession,
    *,
    tenant_id: int,
    month_start: date | None = None,
    month_end: date | None = None,
    today: date | None = None,
) -> DashboardStats:
    anchor = today or await _institution_today(db, tenant_id)
    period_start = month_start or _month_start(anchor)
    period_end = month_end or _month_end(period_start)

    status_counts = await _invoice_status_counts(db, tenant_id)
    total = sum(status_counts.values())
    processed = status_counts.get(InvoiceStatus.PROCESSED, 0)
    exceptions = status_counts.get(InvoiceStatus.EXCEPTION, 0)
    pending = status_counts.get(InvoiceStatus.PENDING, 0)
    duplicates = status_counts.get(InvoiceStatus.DUPLICATE_SKIPPED, 0)
    rejected = status_counts.get(InvoiceStatus.REJECTED, 0)
    pending_approval = sum(
        status_counts.get(s, 0) for s in _APPROVAL_STATUSES
    )
    inbox_count = sum(status_counts.get(s, 0) for s in _INBOX_STATUSES)

    invoices_this_month, _, docs_via_email = await _period_invoice_metrics(
        db, tenant_id, period_start, period_end
    )
    distinct_vendors = await _distinct_vendors_in_period(
        db, tenant_id, period_start, period_end, statuses=_BOOKED_STATUSES
    )
    tenant = await db.get(Tenant, tenant_id)
    reporting_currency = tenant_currency(tenant)
    total_value, value_by_currency = await _sum_value_in_period(
        db, tenant_id, period_start, period_end, base=reporting_currency
    )
    docs_via_upload = await _docs_via_upload(
        db, tenant_id, month_start=period_start, month_end=period_end
    )

    sync_denominator = total - sum(
        status_counts.get(s, 0) for s in _SYNC_EXCLUDED_STATUSES
    )
    synced_percent = (
        round(processed / sync_denominator * 100) if sync_denominator else 0
    )

    rec_balanced, rec_delta = await _reconciliation_for_tenant(db, tenant_id)
    avg_seconds = await _avg_processing_seconds(
        db, tenant_id=tenant_id, month_start=period_start, month_end=period_end
    )
    mailboxes_mapped = await _mailboxes_mapped(db, tenant_id=tenant_id)

    return DashboardStats(
        total_invoices=total,
        invoices_this_month=invoices_this_month,
        processed=processed,
        exceptions=exceptions,
        pending=pending,
        inbox_count=inbox_count,
        duplicates_skipped=duplicates,
        rejected=rejected,
        pending_approval=pending_approval,
        base_currency=reporting_currency,
        total_value=total_value,
        value_by_currency=value_by_currency,
        total_value_aud=total_value,
        synced_percent=synced_percent,
        avg_processing_seconds=avg_seconds,
        last_reconciliation_balanced=rec_balanced,
        reconciliation_delta_dr_cr=rec_delta,
        integrations_connected=_integrations_count(mailboxes_mapped),
        distinct_vendors=distinct_vendors,
        docs_via_email=docs_via_email,
        docs_via_upload=docs_via_upload,
        mailboxes_mapped=mailboxes_mapped,
        active_users=await _active_users(db, tenant_id=tenant_id),
    )


async def _avg_processing_seconds(
    db: AsyncSession,
    *,
    tenant_id: int,
    month_start: date | None = None,
    month_end: date | None = None,
) -> float | None:
    """Mean seconds from invoice create to invoice_processed audit event."""
    processed_log = (
        select(
            AuditLog.invoice_id,
            func.min(AuditLog.created_at).label("processed_at"),
        )
        .join(Invoice, Invoice.id == AuditLog.invoice_id)
        .where(
            AuditLog.invoice_id.isnot(None),
            AuditLog.event == "invoice_processed",
            Invoice.tenant_id == tenant_id,
        )
        .group_by(AuditLog.invoice_id)
        .subquery()
    )
    stmt = (
        select(
            func.avg(
                func.extract(
                    "epoch",
                    processed_log.c.processed_at - Invoice.created_at,
                )
            )
        )
        .select_from(Invoice)
        .join(processed_log, processed_log.c.invoice_id == Invoice.id)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.status == InvoiceStatus.PROCESSED,
        )
    )
    if month_start is not None and month_end is not None:
        lo, hi = _invoice_date_filters(month_start, month_end)
        stmt = stmt.where(lo, hi)
    result = (await db.execute(stmt)).scalar()
    if result is None:
        return None
    return float(result)


_DUPLICATE_ACTIVITY_EVENTS = frozenset(
    {
        "duplicate_skipped",
        "duplicate_in_progress",
        "duplicate_reingest_rejected",
    }
)

_ACTIVITY_NOISE_EVENTS = frozenset(
    {
        "parse_completed",
        "mapping_applied",
        "validation_passed",
        "blob_relocated",
        "vendor_sender_learned",
        "reconciliation_skipped",
        "three_way_match_evaluated",
        "purchase_po_document_synced",
        "purchase_grn_document_synced",
        "purchase_invoice_document_synced",
        "invoices_remapped",
        "vault_migrated",
    }
)


def _activity_item_from_row(
    log: AuditLog,
    vendor: str | None,
    status: InvoiceStatus | None,
    document_ref: str | None,
) -> ActivityItem:
    from app.services.audit.audit_change_summary import summarize_audit_change

    status_schema = (
        InvoiceStatusSchema(status.value) if status is not None else None
    )
    detail = log.detail if isinstance(log.detail, dict) else {}
    ref = (document_ref or "").strip() or None
    if not ref and log.invoice_id is not None:
        ref = f"DOC-{log.invoice_id}"
    return ActivityItem(
        id=log.id,
        invoice_id=log.invoice_id,
        document_ref=ref,
        event=log.event,
        detail=log.detail,
        created_at=log.created_at,
        vendor=vendor,
        status=status_schema,
        summary=summarize_audit_change(log.event, detail),
    )


async def fetch_activity(
    db: AsyncSession, limit: int, *, tenant_id: int
) -> list[ActivityItem]:
    """Recent org activity for dashboard — always surfaces duplicate detections."""
    base = (
        select(AuditLog, Invoice.vendor, Invoice.status, Invoice.document_ref)
        .join(Invoice, Invoice.id == AuditLog.invoice_id)
        .where(
            AuditLog.invoice_id.isnot(None),
            Invoice.tenant_id == tenant_id,
        )
    )

    duplicate_rows = (
        await db.execute(
            base.where(AuditLog.event.in_(_DUPLICATE_ACTIVITY_EVENTS))
            .order_by(AuditLog.created_at.desc())
            .limit(min(limit, 8))
        )
    ).all()

    general_rows = (
        await db.execute(
            base.where(AuditLog.event.notin_(_ACTIVITY_NOISE_EVENTS))
            .order_by(AuditLog.created_at.desc())
            .limit(limit * 2)
        )
    ).all()

    merged: list[ActivityItem] = []
    seen_ids: set[int] = set()
    for log, vendor, status, document_ref in (*duplicate_rows, *general_rows):
        if log.id in seen_ids:
            continue
        seen_ids.add(log.id)
        merged.append(_activity_item_from_row(log, vendor, status, document_ref))
        if len(merged) >= limit:
            break

    merged.sort(key=lambda item: item.created_at, reverse=True)
    return merged[:limit]


async def fetch_top_vendors(
    db: AsyncSession,
    *,
    tenant_id: int,
    limit: int = 5,
    month_start: date | None = None,
    month_end: date | None = None,
) -> list[TopVendorRow]:
    stmt = select(
        func.coalesce(Invoice.vendor, "Unknown"),
        Invoice.total,
        Invoice.currency,
        Invoice.route_target,
    ).where(
        Invoice.tenant_id == tenant_id,
        Invoice.total.isnot(None),
        Invoice.status.in_(_BOOKED_STATUSES),
    )
    if month_start is not None and month_end is not None:
        lo, hi = _invoice_date_filters(month_start, month_end)
        stmt = stmt.where(lo, hi)

    vendor_amounts: dict[str, Decimal] = {}
    vendor_counts: dict[str, int] = {}
    vendor_sales_counts: dict[str, int] = {}
    vendor_purchase_counts: dict[str, int] = {}
    for vendor, total, currency, route_target in (await db.execute(stmt)).all():
        name = str(vendor)
        vendor_amounts[name] = vendor_amounts.get(name, Decimal("0")) + convert_to_base(
            total, currency
        )
        vendor_counts[name] = vendor_counts.get(name, 0) + 1
        route = (route_target or "").strip()
        if route == ROUTE_SALES:
            vendor_sales_counts[name] = vendor_sales_counts.get(name, 0) + 1
        elif route in {ROUTE_PURCHASE, ROUTE_EXPENSES}:
            vendor_purchase_counts[name] = vendor_purchase_counts.get(name, 0) + 1

    ranked = sorted(vendor_amounts.items(), key=lambda item: item[1], reverse=True)[:limit]

    def _counterparty_label(name: str) -> str:
        sales = vendor_sales_counts.get(name, 0)
        purchase = vendor_purchase_counts.get(name, 0)
        if sales > purchase:
            return "Customer"
        if purchase > sales:
            return "Vendor"
        return "Counterparty"

    return [
        TopVendorRow(
            vendor=name,
            amount=amount,
            invoice_count=vendor_counts[name],
            counterparty_label=_counterparty_label(name),
        )
        for name, amount in ranked
    ]


async def fetch_cash_forecast(
    db: AsyncSession, *, tenant_id: int, today: date | None = None
) -> list[CashForecastBucket]:
    anchor = today or await _institution_today(db, tenant_id)
    amounts = {label: Decimal("0") for label, _, _ in _FORECAST_BUCKETS}

    stmt = select(Invoice.due_date, Invoice.total, Invoice.currency).where(
        Invoice.tenant_id == tenant_id,
        Invoice.due_date.isnot(None),
        Invoice.total.isnot(None),
        Invoice.status.in_(_BOOKED_STATUSES),
    )
    for due_date, total, currency in (await db.execute(stmt)).all():
        if due_date is None or total is None:
            continue
        days = (due_date - anchor).days
        amt = convert_to_base(total, currency)
        for label, lo, hi in _FORECAST_BUCKETS:
            if hi is None and days >= lo:
                amounts[label] += amt
                break
            if hi is not None and lo <= days <= hi:
                amounts[label] += amt
                break

    return [CashForecastBucket(label=label, amount=amounts[label]) for label, _, _ in _FORECAST_BUCKETS]


def _sparkline_days(
    month_start: date,
    month_end: date,
    *,
    today: date,
    days: int = 7,
) -> list[date]:
    """Last N calendar days within the period, oldest first."""
    end = min(month_end, today)
    start = max(month_start, end - timedelta(days=days - 1))
    return [start + timedelta(days=i) for i in range(days)]


async def _daily_avg_processing_by_day(
    db: AsyncSession,
    tenant_id: int,
    days_list: list[date],
) -> dict[date, int]:
    if not days_list:
        return {}
    processed_log = (
        select(
            AuditLog.invoice_id,
            func.min(AuditLog.created_at).label("processed_at"),
        )
        .join(Invoice, Invoice.id == AuditLog.invoice_id)
        .where(
            AuditLog.invoice_id.isnot(None),
            AuditLog.event == "invoice_processed",
            Invoice.tenant_id == tenant_id,
        )
        .group_by(AuditLog.invoice_id)
        .subquery()
    )
    stmt = (
        select(
            func.date(processed_log.c.processed_at),
            func.avg(
                func.extract(
                    "epoch",
                    processed_log.c.processed_at - Invoice.created_at,
                )
            ),
        )
        .select_from(Invoice)
        .join(processed_log, processed_log.c.invoice_id == Invoice.id)
        .where(
            Invoice.tenant_id == tenant_id,
            func.date(processed_log.c.processed_at) >= days_list[0],
            func.date(processed_log.c.processed_at) <= days_list[-1],
        )
        .group_by(func.date(processed_log.c.processed_at))
    )
    result: dict[date, int] = {}
    for day, avg_sec in (await db.execute(stmt)).all():
        if day is not None and avg_sec is not None:
            result[day] = max(0, int(round(float(avg_sec))))
    return result


async def _daily_recon_delta_by_day(
    db: AsyncSession,
    tenant_id: int,
    days_list: list[date],
) -> dict[date, int]:
    if not days_list:
        return {}
    stmt = (
        select(
            JournalEntry.date,
            func.coalesce(func.sum(JournalEntry.debit), 0),
            func.coalesce(func.sum(JournalEntry.credit), 0),
        )
        .join(Invoice, Invoice.id == JournalEntry.invoice_id)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.status.in_(_BOOKED_STATUSES),
            JournalEntry.date >= days_list[0],
            JournalEntry.date <= days_list[-1],
        )
        .group_by(JournalEntry.date)
    )
    result: dict[date, int] = {}
    for day, debits, credits in (await db.execute(stmt)).all():
        if day is not None:
            delta = abs(Decimal(str(debits)) - Decimal(str(credits)))
            result[day] = int(delta * 100)
    return result


async def fetch_kpi_sparklines(
    db: AsyncSession,
    *,
    tenant_id: int,
    month_start: date,
    month_end: date,
    today: date | None = None,
    days: int = 7,
) -> KpiSparklines:
    anchor = today or await _institution_today(db, tenant_id)
    days_list = _sparkline_days(month_start, month_end, today=anchor, days=days)
    if not days_list:
        empty = [0] * days
        return KpiSparklines(
            invoice_volume=empty,
            docs_via_email=empty,
            docs_via_upload=empty,
            total_value=empty,
            distinct_vendors=empty,
            mailboxes_active=empty,
            active_users=empty,
            avg_processing_seconds=empty,
            reconciliation_delta=empty,
        )

    window_start, window_end = days_list[0], days_list[-1]
    inv_rows = (
        await db.execute(
            select(
                func.date(Invoice.created_at),
                Invoice.email_sender,
                Invoice.email_message_id,
                Invoice.total,
                Invoice.currency,
                Invoice.vendor,
                Invoice.connected_mailbox_id,
                Invoice.status,
            ).where(
                Invoice.tenant_id == tenant_id,
                func.date(Invoice.created_at) >= window_start,
                func.date(Invoice.created_at) <= window_end,
            )
        )
    ).all()

    by_day: dict[date, list] = {}
    for (
        created,
        email_sender,
        email_message_id,
        total,
        currency,
        vendor,
        mailbox_id,
        status,
    ) in inv_rows:
        if created is None:
            continue
        by_day.setdefault(created, []).append(
            (email_sender, email_message_id, total, currency, vendor, mailbox_id, status)
        )

    avg_by_day = await _daily_avg_processing_by_day(db, tenant_id, days_list)
    recon_by_day = await _daily_recon_delta_by_day(db, tenant_id, days_list)

    volume: list[int] = []
    email_docs: list[int] = []
    upload_docs: list[int] = []
    values: list[int] = []
    vendors: list[int] = []
    mailboxes: list[int] = []
    users: list[int] = []
    avg_proc: list[int] = []
    recon: list[int] = []

    for d in days_list:
        rows = by_day.get(d, [])
        volume.append(len(rows))
        email_docs.append(
            sum(
                1
                for email_sender, email_message_id, _, _, _, mailbox_id, _ in rows
                if _is_email_sourced(email_sender, email_message_id, mailbox_id)
            )
        )
        upload_docs.append(
            sum(
                1
                for email_sender, email_message_id, _, _, _, mailbox_id, _ in rows
                if not _is_email_sourced(email_sender, email_message_id, mailbox_id)
            )
        )
        booked_rows = [row for row in rows if row[6] in _BOOKED_STATUSES]
        values.append(
            int(
                sum(
                    convert_to_base(total, currency)
                    for _, _, total, currency, _, _, _ in booked_rows
                    if total is not None
                )
            )
        )
        vendors.append(
            len({vendor for _, _, _, _, vendor, _, _ in booked_rows if vendor})
        )
        mailboxes.append(
            len({mb for _, _, _, _, _, mb, _ in rows if mb is not None})
        )
        users.append(await _active_users_as_of(db, tenant_id, d))
        avg_proc.append(avg_by_day.get(d, 0))
        recon.append(recon_by_day.get(d, 0))

    return KpiSparklines(
        invoice_volume=volume,
        docs_via_email=email_docs,
        docs_via_upload=upload_docs,
        total_value=values,
        distinct_vendors=vendors,
        mailboxes_active=mailboxes,
        active_users=users,
        avg_processing_seconds=avg_proc,
        reconciliation_delta=recon,
    )


async def fetch_volume_sparkline(
    db: AsyncSession,
    *,
    tenant_id: int,
    month_start: date,
    month_end: date,
    days: int = 7,
) -> list[int]:
    sparklines = await fetch_kpi_sparklines(
        db,
        tenant_id=tenant_id,
        month_start=month_start,
        month_end=month_end,
        days=days,
    )
    return sparklines.invoice_volume


def _anomaly_document_ref(inv: Invoice) -> str:
    return dossier_public_id(inv)


def _anomaly_document_label(inv: Invoice) -> str:
    """Stable vault id first; extracted invoice_no only when it differs."""
    primary = dossier_public_id(inv)
    invoice_no = (inv.invoice_no or "").strip()
    if invoice_no and invoice_no.upper() != primary.upper():
        return f"{primary} · {invoice_no}"
    return primary


def _anomaly_row(*, tag: str, description: str, inv: Invoice) -> AnomalyRow:
    return AnomalyRow(
        tag=tag,
        description=description,
        invoice_id=inv.id,
        document_ref=_anomaly_document_ref(inv),
    )


def _parse_validation_results(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _first_failed_validation(
    raw: str | None,
) -> tuple[str, str] | None:
    for vr in _parse_validation_results(raw):
        if vr.get("passed") or vr.get("skipped"):
            continue
        rule = str(vr.get("rule", "")).strip() or "Validation"
        message = str(vr.get("message", "")).strip() or "Validation failed"
        return rule, message
    return None


def _validation_anomaly_tag(rule: str, message: str) -> str:
    if re.search(r"gst|tax", rule, re.I) or re.search(r"gst|tax", message, re.I):
        return "GST mismatch"
    if rule.upper().startswith("VR-TE"):
        return "Team policy"
    return "Validation"


def _counterparty_unknown_label(route_target: str | None) -> str:
    route = (route_target or "").strip()
    if route == ROUTE_SALES:
        return "Unknown customer"
    if route == ROUTE_TEAM:
        return "Unknown employee"
    return "Unknown vendor"


def _pending_counterparty_tag(route_target: str | None) -> str:
    route = (route_target or "").strip()
    if route == ROUTE_SALES:
        return "Pending customer"
    return "Pending vendor"


def _linkage_anomaly_for_invoice(inv: Invoice) -> AnomalyRow | None:
    """PO/SO linkage gaps — sales and invoice-no paths are not PO-backed."""
    route = (inv.route_target or "").strip()
    label = _anomaly_document_label(inv)
    invoice_no = (inv.invoice_no or "").strip()

    if route == ROUTE_TEAM:
        return None
    if route == ROUTE_SALES:
        if resolve_so_reference_from_invoice(inv) or invoice_no:
            return None
        return _anomaly_row(
            tag="Missing SO",
            description=f"{label} has no sales order reference",
            inv=inv,
        )
    if route == ROUTE_EXPENSES:
        return None
    po_ref = (inv.po_reference or "").strip()
    if po_ref:
        return None
    if invoice_no:
        return None
    return _anomaly_row(
        tag="Missing PO",
        description=f"{label} has no purchase order",
        inv=inv,
    )


async def _routing_anomaly_rows(
    db: AsyncSession,
    *,
    tenant_id: int,
    limit: int,
) -> list[AnomalyRow]:
    invoices = (
        await db.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.evaluation_status.in_(
                    [EVAL_PENDING_VENDOR, EVAL_NEEDS_REVIEW, EVAL_UNMATCHED_EXPENSE_VENDOR]
                ),
                Invoice.status.notin_(_TERMINAL_ANOMALY_STATUSES),
            )
            .order_by(Invoice.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    rows: list[AnomalyRow] = []
    for inv in invoices:
        label = _anomaly_document_label(inv)
        vendor = (inv.vendor or _counterparty_unknown_label(inv.route_target)).strip()
        route = (inv.route_target or "").strip()
        if inv.evaluation_status == EVAL_PENDING_VENDOR:
            register = "customer masters" if route == ROUTE_SALES else "vendor masters"
            rows.append(
                _anomaly_row(
                    tag=_pending_counterparty_tag(inv.route_target),
                    description=f"{label} · {vendor} — register in {register}",
                    inv=inv,
                )
            )
        elif inv.evaluation_status == EVAL_UNMATCHED_EXPENSE_VENDOR:
            rows.append(
                _anomaly_row(
                    tag="Unmatched vendor",
                    description=f"{label} · {vendor} — under hold threshold; register when convenient",
                    inv=inv,
                )
            )
        else:
            route_label = inv.route_target or "unrouted"
            rows.append(
                _anomaly_row(
                    tag="Needs review",
                    description=f"{label} · {vendor} — routed to {route_label}, needs review",
                    inv=inv,
                )
            )
    return rows


async def _duplicate_anomaly_description(
    db: AsyncSession,
    inv: Invoice,
) -> str:
    label = _anomaly_document_label(inv)
    for vr in _parse_validation_results(inv.validation_results):
        if str(vr.get("rule", "")) == "VR02" and not vr.get("passed"):
            message = str(vr.get("message", "")).strip()
            if message:
                return f"{label} — {message}"
    log = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.invoice_id == inv.id,
                AuditLog.event == "duplicate_skipped",
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if log and isinstance(log.detail, dict):
        filename = log.detail.get("filename")
        if filename:
            return f"{label} duplicate skipped — same file as {filename}"
    return f"{label} duplicate skipped"


async def fetch_anomalies(
    db: AsyncSession,
    *,
    tenant_id: int,
    limit: int = 5,
) -> list[AnomalyRow]:
    rows: list[AnomalyRow] = []

    dupes = (
        await db.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                Invoice.status == InvoiceStatus.DUPLICATE_SKIPPED,
            )
            .order_by(Invoice.created_at.desc())
            .limit(3)
        )
    ).scalars().all()
    for inv in dupes:
        rows.append(
            _anomaly_row(
                tag="Duplicate",
                description=await _duplicate_anomaly_description(db, inv),
                inv=inv,
            )
        )

    if len(rows) < limit:
        rows.extend(
            await _routing_anomaly_rows(
                db,
                tenant_id=tenant_id,
                limit=limit - len(rows),
            )
        )

    exc_stmt = (
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.status == InvoiceStatus.EXCEPTION,
        )
        .order_by(Invoice.created_at.desc())
        .limit(10)
    )
    exceptions = (await db.execute(exc_stmt)).scalars().all()
    seen_ids = {row.invoice_id for row in rows if row.invoice_id is not None}
    for inv in exceptions:
        if len(rows) >= limit:
            break
        if inv.id in seen_ids:
            continue
        linkage = _linkage_anomaly_for_invoice(inv)
        if linkage is not None:
            rows.append(linkage)
            continue
        failed = _first_failed_validation(inv.validation_results)
        if failed:
            rule, message = failed
            detail = message if message != "Validation failed" else f"{rule} failed"
            rows.append(
                _anomaly_row(
                    tag=_validation_anomaly_tag(rule, message),
                    description=f"{_anomaly_document_label(inv)} — {detail}",
                    inv=inv,
                )
            )

    if len(rows) < limit and exceptions and not any(
        r.invoice_id == exceptions[0].id for r in rows
    ):
        inv = exceptions[0]
        rows.append(
            _anomaly_row(
                tag="Exception",
                description=f"{_anomaly_document_label(inv)} needs review in Approvals",
                inv=inv,
            )
        )

    return rows[:limit]


async def fetch_mailbox_breakdown(
    db: AsyncSession,
    *,
    tenant_id: int,
    month_start: date,
    month_end: date,
) -> list[MailboxBreakdownRow]:
    mailboxes = (
        await db.execute(
            select(ConnectedMailbox)
            .where(ConnectedMailbox.tenant_id == tenant_id)
            .order_by(ConnectedMailbox.email)
        )
    ).scalars().all()

    lo, hi = _invoice_date_filters(month_start, month_end)
    breakdown: list[MailboxBreakdownRow] = []
    for mb in mailboxes:
        count = (
            await db.execute(
                select(func.count(Invoice.id)).where(
                    Invoice.tenant_id == tenant_id,
                    Invoice.connected_mailbox_id == mb.id,
                    lo,
                    hi,
                )
            )
        ).scalar() or 0
        breakdown.append(
            MailboxBreakdownRow(
                mailbox_id=mb.id,
                email=mb.email,
                display_name=mb.display_name,
                is_active=mb.is_active,
                last_poll_at=mb.last_poll_at,
                document_count=count,
            )
        )
    return breakdown


def _pct_change(current: int | float, previous: int | float) -> float | None:
    if previous == 0:
        return None if current == 0 else 100.0
    return ((current - previous) / previous) * 100.0


def _trend_from_pct(
    pct: float | None,
    *,
    higher_is_better: bool = True,
) -> KpiTrend | None:
    if pct is None:
        return None
    if abs(pct) < 0.5:
        return KpiTrend(direction="flat", text="vs prior month", favorable=True)
    direction = "up" if pct > 0 else "down"
    favorable = (pct > 0) == higher_is_better
    sign = "+" if pct > 0 else ""
    return KpiTrend(
        direction=direction,
        text=f"{sign}{pct:.0f}% vs prior month",
        favorable=favorable,
    )


async def build_kpi_trends(
    db: AsyncSession,
    *,
    tenant_id: int,
    month_start: date,
    month_end: date,
) -> dict[str, KpiTrend]:
    prev_end = month_start - timedelta(days=1)
    prev_start = _month_start(prev_end)

    curr_invoices = await _count_in_period(db, tenant_id, month_start, month_end)
    prev_invoices = await _count_in_period(db, tenant_id, prev_start, prev_end)
    curr_value = float(
        (await _sum_value_in_period(db, tenant_id, month_start, month_end))[0]
    )
    prev_value = float(
        (await _sum_value_in_period(db, tenant_id, prev_start, prev_end))[0]
    )
    curr_email = await _docs_via_email(
        db, tenant_id, month_start=month_start, month_end=month_end
    )
    prev_email = await _docs_via_email(
        db, tenant_id, month_start=prev_start, month_end=prev_end
    )
    curr_upload = await _docs_via_upload(
        db, tenant_id, month_start=month_start, month_end=month_end
    )
    prev_upload = await _docs_via_upload(
        db, tenant_id, month_start=prev_start, month_end=prev_end
    )
    curr_vendors = await _distinct_vendors_in_period(
        db, tenant_id, month_start, month_end, statuses=_BOOKED_STATUSES
    )
    prev_vendors = await _distinct_vendors_in_period(
        db, tenant_id, prev_start, prev_end, statuses=_BOOKED_STATUSES
    )
    curr_avg = await _avg_processing_seconds(
        db, tenant_id=tenant_id, month_start=month_start, month_end=month_end
    )
    prev_avg = await _avg_processing_seconds(
        db, tenant_id=tenant_id, month_start=prev_start, month_end=prev_end
    )
    curr_mailbox_activity = await _mailboxes_with_docs_in_period(
        db, tenant_id, month_start, month_end
    )
    prev_mailbox_activity = await _mailboxes_with_docs_in_period(
        db, tenant_id, prev_start, prev_end
    )
    curr_users = await _active_users_as_of(db, tenant_id, month_end)
    prev_users = await _active_users_as_of(db, tenant_id, prev_end)

    trends: dict[str, KpiTrend] = {}
    mapping = {
        "docs_via_email": (_pct_change(curr_email, prev_email), True),
        "docs_via_upload": (_pct_change(curr_upload, prev_upload), True),
        "total_value": (_pct_change(curr_value, prev_value), True),
        "distinct_vendors": (_pct_change(curr_vendors, prev_vendors), True),
        "invoices_this_month": (_pct_change(curr_invoices, prev_invoices), True),
        "mailboxes_active": (
            _pct_change(curr_mailbox_activity, prev_mailbox_activity),
            True,
        ),
        "active_users": (_pct_change(curr_users, prev_users), True),
    }
    for key, (pct, higher_is_better) in mapping.items():
        trend = _trend_from_pct(pct, higher_is_better=higher_is_better)
        if trend:
            trends[key] = trend

    if curr_avg is not None and prev_avg is not None and prev_avg > 0:
        avg_pct = _pct_change(curr_avg, prev_avg)
        avg_trend = _trend_from_pct(avg_pct, higher_is_better=False)
        if avg_trend:
            trends["avg_processing_seconds"] = avg_trend

    return trends


async def build_overview(
    db: AsyncSession,
    *,
    tenant_id: int,
    activity_limit: int = 8,
    month: str | None = None,
) -> DashboardOverview:
    today = await _institution_today(db, tenant_id)
    month_start, month_end, period = parse_period(month, today=today)
    stats, kpi_sparklines = await asyncio.gather(
        build_stats(
            db,
            tenant_id=tenant_id,
            month_start=month_start,
            month_end=month_end,
            today=today,
        ),
        fetch_kpi_sparklines(
            db,
            tenant_id=tenant_id,
            month_start=month_start,
            month_end=month_end,
            today=today,
        ),
    )
    tenant = await db.get(Tenant, tenant_id)
    labor_rate = tenant_labor_rate_per_hour(tenant)
    (
        panels,
        activity,
        top_vendors,
        cash_forecast,
        mailbox_breakdown,
        anomalies,
        kpi_trends,
        integrations_connected,
    ) = await asyncio.gather(
        build_dashboard_panels(
            db,
            tenant_id=tenant_id,
            month_start=month_start,
            month_end=month_end,
            today=today,
            pending_approval=stats.pending_approval,
            base_currency=stats.base_currency or BASE_CURRENCY,
            labor_rate_per_hour=labor_rate,
            timezone_name=tenant_timezone(tenant),
        ),
        fetch_activity(db, activity_limit, tenant_id=tenant_id),
        fetch_top_vendors(
            db,
            tenant_id=tenant_id,
            limit=5,
            month_start=month_start,
            month_end=month_end,
        ),
        fetch_cash_forecast(db, tenant_id=tenant_id, today=today),
        fetch_mailbox_breakdown(
            db,
            tenant_id=tenant_id,
            month_start=month_start,
            month_end=month_end,
        ),
        fetch_anomalies(db, tenant_id=tenant_id),
        build_kpi_trends(
            db,
            tenant_id=tenant_id,
            month_start=month_start,
            month_end=month_end,
        ),
        _integrations_connected(db, tenant_id),
    )
    return DashboardOverview(
        period=period,
        period_has_data=stats.invoices_this_month > 0,
        cash_forecast_scope="All open payables for your organisation",
        stats=stats,
        activity=activity,
        top_vendors=top_vendors,
        cash_forecast=cash_forecast,
        mailbox_breakdown=mailbox_breakdown,
        anomalies=anomalies,
        kpi_trends=kpi_trends,
        integrations_connected=integrations_connected,
        kpi_sparklines=kpi_sparklines,
        invoice_volume_sparkline=kpi_sparklines.invoice_volume,
        executive_kpis=panels["executive_kpis"],
        capture_sources=panels["capture_sources"],
        risk_compliance=panels["risk_compliance"],
        attention=panels["attention"],
        operations=panels["operations"],
        extraction_quality=panels["extraction_quality"],
        approval_queue=panels["approval_queue"],
        user_layer=panels["user_layer"],
    )
