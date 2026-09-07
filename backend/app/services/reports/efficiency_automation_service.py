"""Efficiency & Automation Value dashboard — reuses audited report definitions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting_sync_job import (
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    AccountingSyncJob,
)
from app.models.audit import AuditLog
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.schemas.efficiency_automation import (
    EfficiencyAutomationDashboard,
    EfficiencyAutomationKpis,
    EfficiencyAutomationMeta,
)
from app.services.reports.cfo_efficiency_assumptions import (
    DOCUMENT_RETENTION_DAYS,
    FTE_HOURS_PER_YEAR,
    MANUAL_COST_PER_INVOICE_BASELINE,
    MANUAL_PROCESSING_MINUTES_BASELINE,
    SYNC_DEAD_LETTER_MIN_ATTEMPTS,
    TOUCHLESS_TARGET_PCT,
)
from app.services.reports.dashboard_service import _institution_today
from app.services.reports.exception_status_catalog_builders import (
    _as_date,
    process_efficiency_slice,
)
from app.services.reports.dashboard_period import resolve_dashboard_period
from app.services.reports.report_catalog import CATALOG_BY_ID
from app.services.reports.team_expense_catalog_builders import build_missing_documents
from app.services.shared.currency import convert_to_base
from app.tenant_settings import tenant_currency, tenant_labor_rate_per_hour

_ZERO = Decimal("0.00")
_MONTH_NAMES = (
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_PROCESSED_EVENT = "invoice_processed"
_DUPLICATE_SKIPPED_EVENT = "duplicate_skipped"


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _pct_improvement(baseline: Decimal, actual: Decimal) -> Decimal | None:
    if baseline <= 0:
        return None
    return _quantize((baseline - actual) / baseline * Decimal("100"))


def _month_start(as_of: date) -> date:
    return date(as_of.year, as_of.month, 1)


def _to_base(amount: Decimal, currency: str | None, *, base: str) -> Decimal:
    return _quantize(convert_to_base(amount, currency, base=base))


@dataclass(frozen=True)
class _ProcessingStats:
    avg_minutes: Decimal | None
    hours_saved: Decimal
    automation_cost_total: Decimal


async def _processed_invoices(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
) -> list[Invoice]:
    rows = (
        await db.execute(
            select(Invoice).where(
                Invoice.tenant_id == tenant_id,
                Invoice.status == InvoiceStatus.PROCESSED,
                Invoice.created_at.is_not(None),
            )
        )
    ).scalars().all()
    return [
        inv
        for inv in rows
        if (day := _as_date(inv.created_at)) is not None and start <= day <= end
    ]


async def _latest_processed_at(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    invoice_ids: list[int],
) -> dict[int, datetime]:
    if not invoice_ids:
        return {}
    rows = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.tenant_id == tenant_id,
                AuditLog.invoice_id.in_(invoice_ids),
                AuditLog.event == _PROCESSED_EVENT,
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        )
    ).scalars().all()
    latest: dict[int, datetime] = {}
    for row in rows:
        if row.invoice_id is None or row.invoice_id in latest:
            continue
        if row.created_at is not None:
            latest[row.invoice_id] = row.created_at
    return latest


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _processing_stats(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    invoices: list[Invoice],
    *,
    base: str,
    labor_rate: float,
) -> _ProcessingStats:
    ids = [inv.id for inv in invoices if inv.id is not None]
    processed_at = await _latest_processed_at(db, tenant_id, ids)
    minute_samples: list[Decimal] = []
    hours_saved = _ZERO
    automation_cost = _ZERO
    rate = Decimal(str(max(0.0, labor_rate)))

    for inv in invoices:
        if inv.id is None or inv.created_at is None:
            continue
        done = processed_at.get(inv.id)
        if done is None:
            continue
        delta = _aware_utc(done) - _aware_utc(inv.created_at)
        minutes = Decimal(str(max(0.0, delta.total_seconds() / 60.0)))
        minute_samples.append(minutes)
        saved = max(_ZERO, MANUAL_PROCESSING_MINUTES_BASELINE - minutes)
        hours_saved += saved / Decimal("60")
        automation_cost += minutes / Decimal("60") * rate

    avg_minutes = None
    if minute_samples:
        avg_minutes = _quantize(
            sum(minute_samples, _ZERO) / Decimal(len(minute_samples))
        )
    return _ProcessingStats(
        avg_minutes=avg_minutes,
        hours_saved=_quantize(hours_saved),
        automation_cost_total=_quantize(automation_cost),
    )


async def _duplicates_prevented(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    *,
    base: str,
) -> tuple[Decimal, int]:
    """Pre-ingestion duplicate blocks via duplicate_skipped audit (not open exceptions)."""
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end, time.max, tzinfo=timezone.utc)
    rows = (
        await db.execute(
            select(AuditLog, Invoice)
            .join(Invoice, Invoice.id == AuditLog.invoice_id)
            .where(
                AuditLog.tenant_id == tenant_id,
                AuditLog.event == _DUPLICATE_SKIPPED_EVENT,
                AuditLog.created_at >= start_dt,
                AuditLog.created_at <= end_dt,
            )
        )
    ).all()
    total = _ZERO
    for _log, inv in rows:
        total += _to_base(Decimal(str(inv.total or 0)), inv.currency, base=base)
    return _quantize(total), len(rows)


def _capture_channel(inv: Invoice) -> str:
    """Same channel bucketing as dashboard capture sources."""
    src = (inv.capture_source or "").strip().lower()
    if src in {"email", "whatsapp", "viber", "slack", "upload"}:
        return src
    if getattr(inv, "whatsapp_connection_id", None):
        return "whatsapp"
    if getattr(inv, "viber_connection_id", None):
        return "viber"
    if getattr(inv, "slack_connection_id", None):
        return "slack"
    if (
        (inv.email_sender and str(inv.email_sender).strip())
        or inv.email_message_id
        or inv.connected_mailbox_id is not None
    ):
        return "email"
    return "upload"


def _capture_channel_counts(invoices: list[Invoice]) -> dict[str, int]:
    counts = {"email": 0, "upload": 0, "whatsapp": 0, "viber": 0, "slack": 0}
    for inv in invoices:
        counts[_capture_channel(inv)] += 1
    return counts


async def _fraud_blocked(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    *,
    base: str,
) -> tuple[Decimal, int]:
    """DT-21 fraud documents still open — distinct from duplicate prevention."""
    rows = (
        await db.execute(
            select(Invoice).where(
                Invoice.tenant_id == tenant_id,
                func.upper(func.coalesce(Invoice.document_type_code, "")) == "DT-21",
                Invoice.status.notin_(
                    [
                        InvoiceStatus.PROCESSED,
                        InvoiceStatus.REJECTED,
                        InvoiceStatus.DUPLICATE_SKIPPED,
                    ]
                ),
                Invoice.created_at.is_not(None),
            )
        )
    ).scalars().all()
    total = _ZERO
    count = 0
    for inv in rows:
        day = _as_date(inv.created_at)
        if day is None or not (start <= day <= end):
            continue
        total += _to_base(Decimal(str(inv.total or 0)), inv.currency, base=base)
        count += 1
    return _quantize(total), count


async def _missing_documents_count(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
) -> int:
    preview, _ = await build_missing_documents(
        db,
        tenant_id,
        CATALOG_BY_ID["missing-documents"],
        start,
        end,
        as_of=True,
    )
    return sum(1 for row in preview.rows if not row.emphasize)


async def _vault_document_count(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    count = (
        await db.execute(
            select(func.count(Invoice.id)).where(
                Invoice.tenant_id == tenant_id,
                Invoice.raw_file_path.isnot(None),
                Invoice.status != InvoiceStatus.REJECTED,
                Invoice.status != InvoiceStatus.DUPLICATE_SKIPPED,
            )
        )
    ).scalar()
    return int(count or 0)


async def _documents_past_retention(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    as_of: date,
) -> int:
    cutoff = as_of - timedelta(days=DOCUMENT_RETENTION_DAYS)
    count = (
        await db.execute(
            select(func.count(Invoice.id)).where(
                Invoice.tenant_id == tenant_id,
                Invoice.raw_file_path.isnot(None),
                Invoice.status != InvoiceStatus.REJECTED,
                Invoice.status != InvoiceStatus.DUPLICATE_SKIPPED,
                func.date(Invoice.created_at) < cutoff,
            )
        )
    ).scalar()
    return int(count or 0)


async def _sync_metrics(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
) -> tuple[Decimal | None, int, str]:
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end, time.max, tzinfo=timezone.utc)
    rows = (
        await db.execute(
            select(AccountingSyncJob).where(
                AccountingSyncJob.tenant_id == tenant_id,
                AccountingSyncJob.created_at >= start_dt,
                AccountingSyncJob.created_at <= end_dt,
                AccountingSyncJob.status.in_(
                    [JOB_STATUS_COMPLETED, JOB_STATUS_FAILED]
                ),
            )
        )
    ).scalars().all()
    if not rows:
        return None, 0, ""
    completed = sum(1 for row in rows if row.status == JOB_STATUS_COMPLETED)
    failed = len(rows) - completed
    success_pct = _quantize(
        Decimal(completed) * Decimal("100") / Decimal(len(rows))
    )
    dead_letter = sum(
        1
        for row in rows
        if row.status == JOB_STATUS_FAILED
        and int(row.attempts or 0) >= SYNC_DEAD_LETTER_MIN_ATTEMPTS
    )
    providers = sorted({(row.provider or "").strip().upper() for row in rows if row.provider})
    label = " & ".join(providers) if providers else ""
    return success_pct, dead_letter, label


async def build_efficiency_automation_dashboard(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    environment_label: str | None = None,
    period: str | None = None,
) -> EfficiencyAutomationDashboard:
    tenant = await db.get(Tenant, tenant_id)
    base = tenant_currency(tenant)
    labor_rate = tenant_labor_rate_per_hour(tenant)
    as_of = await _institution_today(db, tenant_id)
    period_start, period_end, period_label = resolve_dashboard_period(period, as_of)
    mtd_start = _month_start(as_of)

    efficiency = await process_efficiency_slice(db, tenant_id, period_start, period_end)
    mtd_efficiency = await process_efficiency_slice(db, tenant_id, mtd_start, period_end)

    processed_ytd = await _processed_invoices(db, tenant_id, period_start, period_end)
    capture_counts = _capture_channel_counts(processed_ytd)
    proc_stats = await _processing_stats(
        db, tenant_id, processed_ytd, base=base, labor_rate=labor_rate
    )
    docs_ytd = efficiency.processed
    docs_mtd = mtd_efficiency.processed

    cost_per_invoice = None
    cost_improvement = None
    if docs_ytd > 0:
        cost_per_invoice = _quantize(proc_stats.automation_cost_total / Decimal(docs_ytd))
        cost_improvement = _pct_improvement(
            MANUAL_COST_PER_INVOICE_BASELINE, cost_per_invoice
        )

    fte_equiv = None
    if proc_stats.hours_saved > 0 and FTE_HOURS_PER_YEAR > 0:
        fte_equiv = _quantize(proc_stats.hours_saved / FTE_HOURS_PER_YEAR)

    dup_amount, dup_events = await _duplicates_prevented(
        db, tenant_id, period_start, period_end, base=base
    )
    fraud_amount, fraud_events = await _fraud_blocked(
        db, tenant_id, period_start, period_end, base=base
    )
    missing_docs = await _missing_documents_count(
        db, tenant_id, period_start, period_end
    )
    vault_total = await _vault_document_count(db, tenant_id)
    past_retention = await _documents_past_retention(db, tenant_id, as_of)
    sync_pct, dead_letter, sync_label = await _sync_metrics(
        db, tenant_id, period_start, period_end
    )

    automation_savings = proc_stats.automation_cost_total
    if docs_ytd > 0:
        manual_total = MANUAL_COST_PER_INVOICE_BASELINE * Decimal(docs_ytd)
        automation_savings = _quantize(max(_ZERO, manual_total - proc_stats.automation_cost_total))

    notes: list[str] = [
        f"All currency amounts {base}.",
        "Documents processed = Invoice.status PROCESSED with ingest date "
        "(Invoice.created_at) in the window — same definition as Process Efficiency.",
        "Touchless processing % = Straight-through processing % from Process Efficiency "
        "(STP proxy: no invoice_fields_updated and no approval hold). "
        "First-pass validation % is a separate metric from the same report.",
        f"Touchless target {TOUCHLESS_TARGET_PCT}% is a platform constant (not yet configurable).",
        f"Avg processing time uses ingest→invoice_processed audit timestamps; "
        f"documents without a processed event are excluded from the average.",
        f"Manual baselines: {MANUAL_COST_PER_INVOICE_BASELINE} per invoice and "
        f"{MANUAL_PROCESSING_MINUTES_BASELINE} minutes per document "
        f"(shared cfo_efficiency_assumptions).",
        f"Hours saved YTD = Σ(max(0, baseline minutes − actual minutes)) / 60; "
        f"FTE = hours saved ÷ {FTE_HOURS_PER_YEAR} hrs/year.",
        "Duplicates prevented = duplicate_skipped audit events (pre-ingestion blocks); "
        "does not include open duplicate rows on Invoice Exception.",
        "Fraud blocked = DT-21 documents still open in the period.",
        "Missing supporting docs = Missing Documents report row count (live evaluation).",
        f"Documents past retention = vault files older than {DOCUMENT_RETENTION_DAYS} days "
        f"(platform constant; not yet tenant-configurable).",
        "Vault documents = tenant invoices with a stored file (excl. rejected/duplicate shadows).",
        "Capture channel counts = processed documents grouped by ingest channel "
        "(email, upload, WhatsApp, Viber).",
        "Sync success = completed ÷ (completed + failed) accounting sync jobs in period.",
    ]
    coverage_gaps = [
        "discount_capture: no structured vendor discount-term data — card shows honest gap "
        "(consistent with Position & Liquidity).",
        "total_value_delivered: withheld until discount capture is tracked — automation and "
        "prevention subtotals are still exposed separately.",
    ]

    return EfficiencyAutomationDashboard(
        meta=EfficiencyAutomationMeta(
            currency=base,
            period_label=period_label,
            as_of=as_of.isoformat(),
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            month_start=mtd_start.isoformat(),
            environment_label=environment_label,
            coverage_gaps=coverage_gaps,
            notes=notes,
        ),
        kpis=EfficiencyAutomationKpis(
            touchless_processing_pct=efficiency.stp_pct,
            touchless_target_pct=TOUCHLESS_TARGET_PCT,
            first_pass_validation_pct=efficiency.first_pass_pct,
            straight_through_pct=efficiency.stp_pct,
            cost_per_invoice=cost_per_invoice,
            manual_cost_per_invoice_baseline=MANUAL_COST_PER_INVOICE_BASELINE,
            cost_improvement_pct=cost_improvement,
            avg_processing_minutes=proc_stats.avg_minutes,
            manual_processing_minutes_baseline=MANUAL_PROCESSING_MINUTES_BASELINE,
            hours_saved_ytd=proc_stats.hours_saved,
            fte_equivalent=fte_equiv,
            fte_hours_per_year=FTE_HOURS_PER_YEAR,
            documents_processed_ytd=docs_ytd,
            documents_processed_mtd=docs_mtd,
            documents_capture_email=capture_counts["email"],
            documents_capture_upload=capture_counts["upload"],
            documents_capture_whatsapp=capture_counts["whatsapp"],
            documents_capture_viber=capture_counts["viber"],
            documents_capture_slack=capture_counts.get("slack", 0),
            vault_documents_total=vault_total,
            duplicates_prevented_amount=dup_amount,
            duplicates_prevented_events=dup_events,
            fraud_blocked_amount=fraud_amount,
            fraud_blocked_events=fraud_events,
            discount_captured=None,
            discount_available=None,
            total_value_delivered=None,
            automation_savings_amount=automation_savings,
            sync_success_pct=sync_pct,
            sync_dead_letter_count=dead_letter,
            sync_providers_label=sync_label,
            documents_past_retention=past_retention,
            document_retention_days=DOCUMENT_RETENTION_DAYS,
            missing_supporting_docs=missing_docs,
        ),
    )


async def touchless_pct_from_process_efficiency(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
) -> Decimal | None:
    """Reconciliation helper — STP % from Process Efficiency slice."""
    return (await process_efficiency_slice(db, tenant_id, start, end)).stp_pct


async def missing_documents_count_from_report(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
) -> int:
    return await _missing_documents_count(db, tenant_id, start, end)
