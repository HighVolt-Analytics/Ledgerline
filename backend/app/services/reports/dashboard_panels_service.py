"""Dashboard panel aggregates — executive, capture, risk, attention, ops, quality, user-layer."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from statistics import median
from typing import Any, Iterable, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import JournalEntry
from app.models.user import User
from app.schemas.dashboard import (
    ApprovalQueueStats,
    AttentionMetricPayload,
    AttentionPanel,
    AttentionPriority,
    CaptureSourceRow,
    ExecutiveKpiDelta,
    ExecutiveKpis,
    ExtractionQualityPoint,
    OperationsPanel,
    OpsDocTypeRow,
    OpsMemberSnapshot,
    OpsStatusCounts,
    RiskComplianceRow,
    UserLayerMetric,
    UserLayerStages,
)
from app.services.extraction.field_extraction_confidence import (
    compute_extraction_field_confidence,
)
from app.services.invoice.invoice_evaluation_service import (
    EVAL_AUTO_CODED,
    EVAL_AWAITING_CLASSIFICATION,
    EVAL_NEEDS_REVIEW,
    EVAL_PENDING_APPROVAL,
    EVAL_PENDING_VENDOR,
    EVAL_UNMATCHED_EXPENSE_VENDOR,
)
from app.services.reports.dashboard_savings import (
    cost_saved_from_minutes,
    hours_label,
    manual_minutes as channel_manual_minutes,
    minutes_saved_per_doc,
    time_saved_minutes as channel_time_saved,
)
from app.services.shared.currency import sum_amounts_by_currency

CaptureId = Literal["email", "whatsapp", "viber", "upload"]

_CAPTURE_META: list[tuple[CaptureId, str, str]] = [
    ("email", "Email", "/upload?channel=email"),
    ("whatsapp", "WhatsApp", "/upload?channel=whatsapp"),
    ("viber", "Viber", "/upload?channel=viber"),
    ("upload", "Uploads", "/upload?channel=upload"),
]

_REVIEW_EVAL = frozenset(
    {
        EVAL_NEEDS_REVIEW,
        EVAL_AWAITING_CLASSIFICATION,
        EVAL_PENDING_VENDOR,
        EVAL_UNMATCHED_EXPENSE_VENDOR,
    }
)
_APPROVAL_EVAL = frozenset({EVAL_PENDING_APPROVAL})
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
_POSTING_STATUSES = frozenset(
    {
        InvoiceStatus.JOURNALING,
        InvoiceStatus.RECONCILING,
    }
)

_HEADER_FIELDS = (
    "vendor",
    "invoice_no",
    "invoice_date",
    "due_date",
    "currency",
    "po_reference",
)
_TAX_FIELDS = ("gst", "subtotal", "total")
_LINE_FIELDS = ("line_items",)
_GL_FIELDS = ("account_code", "account_name")

_EXTRACTION_SAMPLE_LIMIT = 80


def _normalize_channel(inv: Invoice) -> CaptureId:
    src = (inv.capture_source or "").strip().lower()
    if src in {"email", "whatsapp", "viber", "upload"}:
        return src  # type: ignore[return-value]
    if getattr(inv, "whatsapp_connection_id", None):
        return "whatsapp"
    if getattr(inv, "viber_connection_id", None):
        return "viber"
    if (
        (inv.email_sender and str(inv.email_sender).strip())
        or inv.email_message_id
        or inv.connected_mailbox_id is not None
    ):
        return "email"
    return "upload"


def _doc_type_bucket(inv: Invoice) -> str:
    kind = (inv.team_expense_kind or "").strip().lower()
    if kind in {"advance", "claim", "invoice"}:
        return kind
    if (inv.route_target or "").strip().lower().find("team") >= 0:
        return "claim"
    return "invoice"


def _member_key(inv: Invoice) -> tuple[str, str]:
    email = (inv.uploaded_by_email or inv.employee_email or "").strip().lower()
    name = (inv.uploaded_by_name or "").strip()
    if email:
        label = name or email.split("@")[0]
        return email, label.title() if label == email.split("@")[0] else label
    if name:
        return f"name:{name.casefold()}", name
    return "unassigned", "Unassigned"


def _ops_status_key(inv: Invoice, *, has_journal: bool) -> str:
    if inv.status == InvoiceStatus.REJECTED:
        return "rejected"
    if inv.status == InvoiceStatus.PROCESSED:
        return "posted" if has_journal else "processed"
    if (
        inv.status in {InvoiceStatus.EXCEPTION, InvoiceStatus.DUPLICATE_SKIPPED}
        or (inv.evaluation_status or "") in _APPROVAL_EVAL
    ):
        return "approvals_pending"
    if inv.status in _INBOX_STATUSES or (inv.evaluation_status or "") in _REVIEW_EVAL:
        return "review_pending"
    return "review_pending"


def _pipeline_stage(inv: Invoice, *, has_journal: bool, in_payment_queue: bool) -> str:
    if in_payment_queue:
        return "pending_payment"
    if inv.status in _POSTING_STATUSES or (
        inv.status == InvoiceStatus.PROCESSED and not has_journal
    ):
        return "pending_posting"
    if (
        inv.status in {InvoiceStatus.EXCEPTION, InvoiceStatus.DUPLICATE_SKIPPED}
        or (inv.evaluation_status or "") in _APPROVAL_EVAL
    ):
        return "pending_approval"
    if (inv.evaluation_status or "") in _REVIEW_EVAL or inv.status in {
        InvoiceStatus.PENDING,
        InvoiceStatus.PARSING,
        InvoiceStatus.VALIDATING,
        InvoiceStatus.MAPPING,
    }:
        return "pending_confirmation"
    return "document_fetched"


def _empty_ops_counts() -> dict[str, int]:
    return {
        "processed": 0,
        "posted": 0,
        "rejected": 0,
        "review_pending": 0,
        "approvals_pending": 0,
    }


def _empty_stages() -> dict[str, int]:
    return {
        "document_fetched": 0,
        "pending_confirmation": 0,
        "pending_approval": 0,
        "pending_posting": 0,
        "pending_payment": 0,
    }


def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None if current == 0 else 100.0
    return ((current - previous) / previous) * 100.0


def _delta_from_pct(
    pct: float | None,
    *,
    higher_is_better: bool = True,
    unit: str = "%",
) -> ExecutiveKpiDelta | None:
    if pct is None:
        return ExecutiveKpiDelta(direction="flat", text="vs prior period", favorable=True)
    direction: Literal["up", "down", "flat"]
    if abs(pct) < 0.5:
        direction = "flat"
    elif pct > 0:
        direction = "up"
    else:
        direction = "down"
    favorable = (pct >= 0) if higher_is_better else (pct <= 0)
    if unit == "pts":
        text = f"{abs(pct):.1f} pts vs. prior period"
    else:
        text = f"{abs(pct):.0f}% vs. prior period"
    return ExecutiveKpiDelta(direction=direction, text=text, favorable=favorable)


def _format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    mins, secs = divmod(total, 60)
    if mins < 60:
        return f"{mins}m {secs:02d}s" if secs else f"{mins}m"
    hours, mins = divmod(mins, 60)
    return f"{hours}h {mins}m"


def _format_median_age(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    return _format_duration(seconds)


def _format_compact_money(amount: Decimal, currency: str) -> str:
    value = float(amount)
    sym = {"AUD": "A$", "USD": "$", "SGD": "S$", "INR": "₹", "EUR": "€", "GBP": "£"}.get(
        (currency or "").upper(), f"{currency} " if currency else ""
    )
    abs_v = abs(value)
    if abs_v >= 100_000 and (currency or "").upper() == "INR":
        lakhs = abs_v / 100_000
        return f"{sym}{lakhs:.2f}L"
    if abs_v >= 1_000_000:
        return f"{sym}{abs_v / 1_000_000:.2f}M"
    if abs_v >= 1_000:
        return f"{sym}{abs_v / 1_000:.1f}k"
    return f"{sym}{abs_v:,.0f}"


def _invoice_date_filters(month_start: date, month_end: date):
    return (
        func.date(Invoice.created_at) >= month_start,
        func.date(Invoice.created_at) <= month_end,
    )


async def _load_period_invoices(
    db: AsyncSession,
    *,
    tenant_id: Any,
    start: date,
    end: date,
) -> list[Invoice]:
    lo, hi = _invoice_date_filters(start, end)
    rows = (
        await db.execute(
            select(Invoice).where(Invoice.tenant_id == tenant_id, lo, hi)
        )
    ).scalars().all()
    return list(rows)


async def _journaled_invoice_ids(
    db: AsyncSession, *, tenant_id: Any, invoice_ids: Iterable[int]
) -> set[int]:
    ids = [i for i in invoice_ids if i]
    if not ids:
        return set()
    rows = (
        await db.execute(
            select(JournalEntry.invoice_id)
            .join(Invoice, Invoice.id == JournalEntry.invoice_id)
            .where(
                Invoice.tenant_id == tenant_id,
                JournalEntry.invoice_id.in_(ids),
            )
            .distinct()
        )
    ).all()
    return {int(r[0]) for r in rows if r[0] is not None}


async def _payment_queue_invoice_ids(
    db: AsyncSession, *, tenant_id: Any
) -> set[int]:
    try:
        from app.models.payment import Payment

        rows = (
            await db.execute(
                select(Payment.invoice_id).where(
                    Payment.tenant_id == tenant_id,
                    Payment.invoice_id.isnot(None),
                )
            )
        ).all()
        ids = {int(r[0]) for r in rows if r[0] is not None}
        if ids:
            return ids
    except Exception:
        pass
    rows = (
        await db.execute(
            select(Invoice.id).where(
                Invoice.tenant_id == tenant_id,
                Invoice.status == InvoiceStatus.PROCESSED,
                Invoice.due_date.isnot(None),
                Invoice.total.isnot(None),
            )
        )
    ).all()
    return {int(r[0]) for r in rows if r[0] is not None}


def _channel_counts(invoices: list[Invoice]) -> dict[CaptureId, int]:
    counts: dict[CaptureId, int] = {
        "email": 0,
        "whatsapp": 0,
        "viber": 0,
        "upload": 0,
    }
    for inv in invoices:
        counts[_normalize_channel(inv)] += 1
    return counts


def build_capture_sources(
    invoices: list[Invoice],
    *,
    actual_processing_minutes: float | None,
) -> list[CaptureSourceRow]:
    counts = _channel_counts(invoices)
    rows: list[CaptureSourceRow] = []
    for channel_id, label, href in _CAPTURE_META:
        docs = counts[channel_id]
        saved = channel_time_saved(
            docs,
            channel_id,
            actual_processing_minutes=actual_processing_minutes,
        )
        manual = channel_manual_minutes(docs, channel_id)
        avg = minutes_saved_per_doc(
            channel_id, actual_processing_minutes=actual_processing_minutes
        )
        rows.append(
            CaptureSourceRow(
                id=channel_id,
                label=label,
                document_count=docs,
                avg_time_saved_minutes=avg,
                time_saved_minutes=saved,
                manual_minutes=manual,
                cost_saved=cost_saved_from_minutes(saved),
                href=href,
            )
        )
    return rows


def build_executive_kpis(
    *,
    current_invoices: list[Invoice],
    prior_invoices: list[Invoice],
    actual_processing_minutes: float | None,
    prior_actual_processing_minutes: float | None,
) -> ExecutiveKpis:
    docs = len(current_invoices)
    prior_docs = len(prior_invoices)
    auto = sum(
        1
        for inv in current_invoices
        if (inv.evaluation_status or "").strip() == EVAL_AUTO_CODED
        or (
            inv.status == InvoiceStatus.PROCESSED
            and (inv.evaluation_status or "").strip()
            not in _REVIEW_EVAL | _APPROVAL_EVAL
        )
    )
    prior_auto = sum(
        1
        for inv in prior_invoices
        if (inv.evaluation_status or "").strip() == EVAL_AUTO_CODED
        or (
            inv.status == InvoiceStatus.PROCESSED
            and (inv.evaluation_status or "").strip()
            not in _REVIEW_EVAL | _APPROVAL_EVAL
        )
    )
    auto_pct = round((auto / docs) * 100) if docs else 0
    prior_auto_pct = round((prior_auto / prior_docs) * 100) if prior_docs else 0

    # Weighted time saved across channels.
    total_saved = 0
    for inv in current_invoices:
        total_saved += minutes_saved_per_doc(
            _normalize_channel(inv),
            actual_processing_minutes=actual_processing_minutes,
        )
    avg_saved = round(total_saved / docs) if docs else 0
    docs_delta = _delta_from_pct(_pct_change(docs, prior_docs), higher_is_better=True)
    auto_delta = _delta_from_pct(
        None if prior_docs == 0 and docs == 0 else float(auto_pct - prior_auto_pct),
        higher_is_better=True,
        unit="pts",
    )
    if prior_docs == 0 and docs == 0:
        auto_delta = ExecutiveKpiDelta(
            direction="flat", text="vs. prior period", favorable=True
        )
    elif prior_docs == 0:
        auto_delta = ExecutiveKpiDelta(
            direction="up" if auto_pct > 0 else "flat",
            text=f"{auto_pct} pts vs. prior period" if auto_pct else "vs. prior period",
            favorable=True,
        )

    return ExecutiveKpis(
        documents_processed=docs,
        documents_delta=docs_delta,
        time_saved_minutes=total_saved,
        time_saved_hours_label=hours_label(total_saved),
        avg_time_saved_per_doc_minutes=avg_saved,
        automation_efficiency_pct=auto_pct,
        automation_delta=auto_delta,
        cost_saved=cost_saved_from_minutes(total_saved),
    )


async def build_risk_compliance(
    db: AsyncSession,
    *,
    tenant_id: Any,
    month_start: date,
    month_end: date,
    invoices: list[Invoice],
) -> list[RiskComplianceRow]:
    lo, hi = _invoice_date_filters(month_start, month_end)

    dupes = sum(
        1
        for inv in invoices
        if inv.status == InvoiceStatus.DUPLICATE_SKIPPED or inv.duplicate_review_suggested
    )
    # Also count open duplicate_review outside period-received if flagged in period statuses.
    extra_dupes = (
        await db.execute(
            select(func.count(Invoice.id)).where(
                Invoice.tenant_id == tenant_id,
                Invoice.duplicate_review_suggested.is_(True),
                Invoice.status != InvoiceStatus.DUPLICATE_SKIPPED,
                lo,
                hi,
            )
        )
    ).scalar() or 0
    # Avoid double-counting invoices already in `invoices` with the flag.
    flagged_in_period = sum(
        1
        for inv in invoices
        if inv.duplicate_review_suggested and inv.status != InvoiceStatus.DUPLICATE_SKIPPED
    )
    if extra_dupes > flagged_in_period:
        dupes += extra_dupes - flagged_in_period

    fraud = sum(
        1
        for inv in invoices
        if (inv.document_type_code or "").strip().upper() == "DT-21"
        and inv.status
        not in {InvoiceStatus.PROCESSED, InvoiceStatus.REJECTED, InvoiceStatus.DUPLICATE_SKIPPED}
    )
    bank = sum(
        1
        for inv in invoices
        if (inv.document_type_code or "").strip().upper() == "DT-23"
    )

    # New counterparties: vendors whose first invoice for the tenant falls in this period.
    vendors_in_period = {
        (inv.vendor or "").strip()
        for inv in invoices
        if (inv.vendor or "").strip()
    }
    new_cp = 0
    if vendors_in_period:
        first_seen = (
            await db.execute(
                select(Invoice.vendor, func.min(func.date(Invoice.created_at)))
                .where(
                    Invoice.tenant_id == tenant_id,
                    Invoice.vendor.in_(list(vendors_in_period)),
                )
                .group_by(Invoice.vendor)
            )
        ).all()
        for vendor, first_day in first_seen:
            if first_day is None:
                continue
            if isinstance(first_day, str):
                try:
                    first_day = date.fromisoformat(first_day[:10])
                except ValueError:
                    continue
            elif isinstance(first_day, datetime):
                first_day = first_day.date()
            if month_start <= first_day <= month_end:
                new_cp += 1

    return [
        RiskComplianceRow(
            id="duplicates",
            label="Duplicate documents",
            count=dupes,
            href="/approvals",
            badge="Review",
        ),
        RiskComplianceRow(
            id="fraud",
            label="Fraud invoices",
            count=fraud,
            href="/upload?view=detailed&q=DT-21",
            badge="Urgent",
        ),
        RiskComplianceRow(
            id="bank",
            label="Bank changes",
            count=bank,
            href="/upload?view=detailed&q=DT-23",
            badge="Monitor",
        ),
        RiskComplianceRow(
            id="counterparties",
            label="New counterparties",
            count=new_cp,
            href="/creations?tab=vendors",
            badge="New",
        ),
    ]


def build_attention_panel(
    *,
    risk_rows: list[RiskComplianceRow],
    pending_approval: int,
    processed_bars: list[int],
    turnaround_bars: list[int],
    processed_today: int,
    processed_yesterday: int,
    avg_turnaround_seconds: float | None,
    prior_avg_turnaround_seconds: float | None,
) -> AttentionPanel:
    by_id = {r.id: r.count for r in risk_rows}
    bank = by_id.get("bank", 0)
    dupes = by_id.get("duplicates", 0)
    fraud = by_id.get("fraud", 0)

    if pending_approval > 0:
        parts: list[str] = []
        if bank:
            parts.append(
                f"{bank} bank-account change{'s' if bank != 1 else ''}"
            )
        if dupes:
            parts.append(
                f"{dupes} duplicate-risk signal{'s' if dupes != 1 else ''}"
            )
        if fraud:
            parts.append(f"{fraud} fraud-risk document{'s' if fraud != 1 else ''}")
        if not parts:
            body = "Open the approvals queue to clear exceptions."
        elif len(parts) == 1:
            body = (
                f"{parts[0][0].upper()}{parts[0][1:]} need attention. "
                "Review them before the next payment run."
            )
        elif len(parts) == 2:
            body = (
                f"{parts[0][0].upper()}{parts[0][1:]} and {parts[1]}. "
                "Review them before the next payment run."
            )
        else:
            joined = f"{', '.join(parts[:-1])}, and {parts[-1]}"
            body = f"{joined[0].upper()}{joined[1:]}. Review them before the next payment run."
        title = (
            "1 invoice needs your approval."
            if pending_approval == 1
            else f"{pending_approval} invoices need your approval."
        )
        priority = AttentionPriority(
            title=title,
            body=body,
            cta_label="Review exceptions",
            cta_href="/approvals",
        )
    elif bank or dupes or fraud:
        total_flags = bank + dupes + fraud
        priority = AttentionPriority(
            title=f"{total_flags} item{'s' if total_flags != 1 else ''} need attention.",
            body="Review risk flags before the next payment run.",
            cta_label="Review exceptions",
            cta_href="/approvals",
        )
    else:
        priority = AttentionPriority(
            title="You're clear for now.",
            body="No urgent approvals or risk flags in this period.",
            cta_label="View documents",
            cta_href="/upload",
        )

    proc_pct = _pct_change(processed_today, processed_yesterday)
    if proc_pct is None:
        proc_delta = "vs. yesterday"
        proc_good = True
    else:
        proc_delta = f"{abs(proc_pct):.0f}% vs. yesterday"
        proc_good = proc_pct >= 0

    turn_delta_text = "vs. last week"
    turn_down = False
    turn_good = True
    if (
        avg_turnaround_seconds is not None
        and prior_avg_turnaround_seconds is not None
        and prior_avg_turnaround_seconds > 0
    ):
        delta_sec = prior_avg_turnaround_seconds - avg_turnaround_seconds
        turn_down = delta_sec > 0
        turn_good = delta_sec >= 0
        abs_delta = abs(int(round(delta_sec)))
        if abs_delta < 60:
            turn_delta_text = f"{abs_delta}s {'faster' if turn_down else 'slower'} this week"
        else:
            turn_delta_text = (
                f"{abs_delta // 60}m {'faster' if turn_down else 'slower'} this week"
            )

    bars_proc = processed_bars[-7:] if processed_bars else [0] * 7
    while len(bars_proc) < 7:
        bars_proc = [0, *bars_proc]
    bars_turn = turnaround_bars[-7:] if turnaround_bars else [0] * 7
    while len(bars_turn) < 7:
        bars_turn = [0, *bars_turn]

    return AttentionPanel(
        priority=priority,
        processed=AttentionMetricPayload(
            label="Processed today",
            value=str(processed_today),
            delta_text=proc_delta,
            delta_good=proc_good,
            bars=bars_proc[-7:],
        ),
        turnaround=AttentionMetricPayload(
            label="Average turnaround",
            value=_format_duration(avg_turnaround_seconds),
            delta_text=turn_delta_text,
            delta_down=turn_down,
            delta_good=turn_good,
            bars=bars_turn[-7:],
        ),
    )


def _build_member_snapshots(
    invoices: list[Invoice],
    *,
    journaled_ids: set[int],
    actual_processing_minutes: float | None,
    tenant_users: list[tuple[str, str]],
) -> list[OpsMemberSnapshot]:
    # member_id -> doc_type -> status -> count
    buckets: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(_empty_ops_counts)
    )
    labels: dict[str, str] = {"all": "All team members"}
    member_docs: dict[str, list[Invoice]] = defaultdict(list)

    for inv in invoices:
        mid, label = _member_key(inv)
        labels[mid] = label
        member_docs[mid].append(inv)
        member_docs["all"].append(inv)
        dtype = _doc_type_bucket(inv)
        status = _ops_status_key(inv, has_journal=inv.id in journaled_ids)
        buckets[mid][dtype][status] += 1
        buckets["all"][dtype][status] += 1

    # Ensure known users appear even with zero docs.
    for email, name in tenant_users:
        key = email.strip().lower()
        if key and key not in labels:
            labels[key] = name or key.split("@")[0].title()
            buckets.setdefault(key, defaultdict(_empty_ops_counts))

    def snapshot_for(member_id: str) -> OpsMemberSnapshot:
        by_type = buckets.get(member_id, {})
        docs = member_docs.get(member_id, [])
        doc_rows: list[OpsDocTypeRow] = []
        for dtype, dtype_label in (
            ("invoice", "Invoice"),
            ("advance", "Advance"),
            ("claim", "Claim"),
        ):
            counts = by_type.get(dtype) or _empty_ops_counts()
            doc_rows.append(
                OpsDocTypeRow(
                    id=dtype,
                    label=dtype_label,
                    counts=OpsStatusCounts(**counts),
                )
            )
        processed = sum(
            1 for inv in docs if inv.status == InvoiceStatus.PROCESSED
        )
        auto = sum(
            1
            for inv in docs
            if (inv.evaluation_status or "").strip() == EVAL_AUTO_CODED
            or (
                inv.status == InvoiceStatus.PROCESSED
                and (inv.evaluation_status or "").strip()
                not in _REVIEW_EVAL | _APPROVAL_EVAL
            )
        )
        pending = sum(
            (by_type.get(dt) or {}).get("review_pending", 0)
            + (by_type.get(dt) or {}).get("approvals_pending", 0)
            for dt in ("invoice", "advance", "claim")
        )
        saved = sum(
            minutes_saved_per_doc(
                _normalize_channel(inv),
                actual_processing_minutes=actual_processing_minutes,
            )
            for inv in docs
        )
        return OpsMemberSnapshot(
            id=member_id,
            label=labels.get(member_id, member_id),
            documents_processed=processed if member_id != "all" else sum(
                1 for inv in docs if inv.status == InvoiceStatus.PROCESSED
            ),
            time_saved_minutes=saved,
            automation_rate_pct=round((auto / len(docs)) * 100) if docs else 0,
            pending_actions=pending,
            accuracy_pct=0,
            by_doc_type=doc_rows,
        )

    ordered_ids = ["all"] + sorted(
        [k for k in labels if k != "all"],
        key=lambda k: labels[k].casefold(),
    )
    return [snapshot_for(mid) for mid in ordered_ids]


async def build_operations_panel(
    db: AsyncSession,
    *,
    tenant_id: Any,
    month_start: date,
    month_end: date,
    today: date,
    actual_processing_minutes: float | None,
) -> OperationsPanel:
    users = (
        await db.execute(
            select(User.email, User.full_name).where(User.tenant_id == tenant_id)
        )
    ).all()
    tenant_users = [
        (str(email or ""), str(full_name or ""))
        for email, full_name in users
        if email
    ]

    windows: dict[str, list[OpsMemberSnapshot]] = {}
    ranges = {
        "7d": (today - timedelta(days=6), today),
        "30d": (today - timedelta(days=29), today),
        "month": (month_start, month_end),
    }
    for key, (start, end) in ranges.items():
        invoices = await _load_period_invoices(
            db, tenant_id=tenant_id, start=start, end=end
        )
        journaled = await _journaled_invoice_ids(
            db, tenant_id=tenant_id, invoice_ids=(inv.id for inv in invoices)
        )
        windows[key] = _build_member_snapshots(
            invoices,
            journaled_ids=journaled,
            actual_processing_minutes=actual_processing_minutes,
            tenant_users=tenant_users,
        )
    return OperationsPanel(windows=windows)


async def build_extraction_quality(
    db: AsyncSession,
    *,
    tenant_id: Any,
    month_start: date,
    month_end: date,
) -> list[ExtractionQualityPoint]:
    lo, hi = _invoice_date_filters(month_start, month_end)
    invoices = (
        await db.execute(
            select(Invoice)
            .where(
                Invoice.tenant_id == tenant_id,
                lo,
                hi,
                Invoice.status.notin_(
                    [InvoiceStatus.PENDING, InvoiceStatus.PARSING]
                ),
            )
            .order_by(Invoice.created_at.desc())
            .limit(_EXTRACTION_SAMPLE_LIMIT)
        )
    ).scalars().all()
    if not invoices:
        return [
            ExtractionQualityPoint(metric="Header", accuracy=0.0),
            ExtractionQualityPoint(metric="Line items", accuracy=0.0),
            ExtractionQualityPoint(metric="Tax/GST", accuracy=0.0),
            ExtractionQualityPoint(metric="GL coding", accuracy=0.0),
        ]

    groups = {
        "Header": _HEADER_FIELDS,
        "Line items": _LINE_FIELDS,
        "Tax/GST": _TAX_FIELDS,
        "GL coding": _GL_FIELDS,
    }
    totals: dict[str, list[float]] = {k: [] for k in groups}
    for inv in invoices:
        scores = compute_extraction_field_confidence(inv)
        for metric, fields in groups.items():
            vals = [scores[f] for f in fields if f in scores]
            if vals:
                totals[metric].append(sum(vals) / len(vals))

    return [
        ExtractionQualityPoint(
            metric=metric,
            accuracy=round(sum(vals) / len(vals), 1) if vals else 0.0,
        )
        for metric, vals in totals.items()
    ]


async def build_approval_queue(
    db: AsyncSession,
    *,
    tenant_id: Any,
    base_currency: str,
) -> ApprovalQueueStats:
    rows = (
        await db.execute(
            select(Invoice).where(
                Invoice.tenant_id == tenant_id,
                or_(
                    Invoice.status.in_(list(_APPROVAL_STATUSES)),
                    Invoice.evaluation_status == EVAL_PENDING_APPROVAL,
                ),
            )
        )
    ).scalars().all()
    pending = len(rows)
    if pending == 0:
        return ApprovalQueueStats(pending=0, value_label="—", median_time_label="—")

    amounts = [(inv.currency, inv.total) for inv in rows if inv.total is not None]
    total_value, _ = sum_amounts_by_currency(amounts, base=base_currency)
    now = datetime.now(timezone.utc)
    ages: list[float] = []
    for inv in rows:
        created = inv.created_at
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        ages.append(max(0.0, (now - created).total_seconds()))
    med = median(ages) if ages else None
    return ApprovalQueueStats(
        pending=pending,
        value_label=_format_compact_money(total_value, base_currency),
        median_time_label=_format_median_age(med),
    )


async def build_user_layer(
    db: AsyncSession,
    *,
    tenant_id: Any,
    month_start: date,
    month_end: date,
    invoices: list[Invoice],
) -> list[UserLayerMetric]:
    journaled = await _journaled_invoice_ids(
        db, tenant_id=tenant_id, invoice_ids=(inv.id for inv in invoices)
    )
    payment_ids = await _payment_queue_invoice_ids(db, tenant_id=tenant_id)

    def stage_for(inv: Invoice) -> str:
        return _pipeline_stage(
            inv,
            has_journal=inv.id in journaled,
            in_payment_queue=inv.id in payment_ids,
        )

    # Metric collectors: for each stage, accumulate a set or count.
    email_sets: dict[str, set[str]] = {k: set() for k in _empty_stages()}
    phone_sets: dict[str, set[str]] = {k: set() for k in _empty_stages()}
    doc_type_sets: dict[str, set[str]] = {k: set() for k in _empty_stages()}
    vendor_sets: dict[str, set[str]] = {k: set() for k in _empty_stages()}
    handoff_counts: dict[str, int] = _empty_stages()

    # document_fetched always includes all period invoices for coverage metrics.
    for inv in invoices:
        stage = stage_for(inv)
        stages_to_count = {"document_fetched", stage}

        email = (inv.email_sender or inv.employee_email or "").strip().lower()
        phone_token = None
        if _normalize_channel(inv) in {"whatsapp", "viber"}:
            phone_token = (
                f"wa:{inv.whatsapp_connection_id}"
                if inv.whatsapp_connection_id
                else f"vb:{inv.viber_connection_id}"
            )
        dt = (inv.document_type_code or "").strip().upper() or "UNKNOWN"
        vendor = (inv.vendor or "").strip()
        is_handoff = _normalize_channel(inv) == "upload" or (
            (inv.evaluation_status or "") in _REVIEW_EVAL
        )

        for st in stages_to_count:
            if email:
                email_sets[st].add(email)
            if phone_token:
                phone_sets[st].add(phone_token)
            if dt:
                doc_type_sets[st].add(dt)
            if vendor:
                vendor_sets[st].add(vendor)
            if is_handoff:
                handoff_counts[st] += 1

    def stages_from_sets(sets: dict[str, set[str]]) -> UserLayerStages:
        return UserLayerStages(
            document_fetched=len(sets["document_fetched"]),
            pending_confirmation=len(sets["pending_confirmation"]),
            pending_approval=len(sets["pending_approval"]),
            pending_posting=len(sets["pending_posting"]),
            pending_payment=len(sets["pending_payment"]),
        )

    return [
        UserLayerMetric(
            id="email_mapped",
            label="No. of E-mail ID Mapped",
            stages=stages_from_sets(email_sets),
        ),
        UserLayerMetric(
            id="phone_synced",
            label="Phone no. synched",
            stages=stages_from_sets(phone_sets),
        ),
        UserLayerMetric(
            id="doc_types",
            label="No. of Doc Types",
            stages=stages_from_sets(doc_type_sets),
        ),
        UserLayerMetric(
            id="manual_handoff",
            label="Manual Handoff",
            stages=UserLayerStages(**handoff_counts),
        ),
        UserLayerMetric(
            id="vendors",
            label="No of Vendors",
            stages=stages_from_sets(vendor_sets),
        ),
    ]


async def count_processed_on_day(
    db: AsyncSession,
    *,
    tenant_id: Any,
    day: date,
) -> int:
    from app.models.audit import AuditLog

    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return (
        await db.execute(
            select(func.count(func.distinct(AuditLog.invoice_id)))
            .select_from(AuditLog)
            .join(Invoice, Invoice.id == AuditLog.invoice_id)
            .where(
                Invoice.tenant_id == tenant_id,
                AuditLog.event == "invoice_processed",
                AuditLog.created_at >= start,
                AuditLog.created_at < end,
            )
        )
    ).scalar() or 0


async def build_dashboard_panels(
    db: AsyncSession,
    *,
    tenant_id: Any,
    month_start: date,
    month_end: date,
    today: date,
    pending_approval: int,
    avg_processing_seconds: float | None,
    prior_avg_processing_seconds: float | None,
    invoice_volume_sparkline: list[int],
    avg_processing_sparkline: list[int],
    base_currency: str,
) -> dict[str, Any]:
    """Build all new overview panel payloads."""
    prev_end = month_start - timedelta(days=1)
    prev_start = prev_end.replace(day=1)

    current = await _load_period_invoices(
        db, tenant_id=tenant_id, start=month_start, end=month_end
    )
    prior = await _load_period_invoices(
        db, tenant_id=tenant_id, start=prev_start, end=prev_end
    )

    actual_min = (
        None
        if avg_processing_seconds is None
        else max(0.0, avg_processing_seconds / 60.0)
    )
    prior_actual_min = (
        None
        if prior_avg_processing_seconds is None
        else max(0.0, prior_avg_processing_seconds / 60.0)
    )

    capture_sources = build_capture_sources(
        current, actual_processing_minutes=actual_min
    )
    executive_kpis = build_executive_kpis(
        current_invoices=current,
        prior_invoices=prior,
        actual_processing_minutes=actual_min,
        prior_actual_processing_minutes=prior_actual_min,
    )
    risk_compliance = await build_risk_compliance(
        db,
        tenant_id=tenant_id,
        month_start=month_start,
        month_end=month_end,
        invoices=current,
    )

    processed_today = await count_processed_on_day(
        db, tenant_id=tenant_id, day=today
    )
    processed_yesterday = await count_processed_on_day(
        db, tenant_id=tenant_id, day=today - timedelta(days=1)
    )
    # Prefer real processed-per-day bars when sparkline is volume-based; still usable.
    processed_bars = list(invoice_volume_sparkline[-7:] or [0] * 7)
    while len(processed_bars) < 7:
        processed_bars = [0, *processed_bars]
    processed_bars = [*processed_bars[:-1], processed_today]

    attention = build_attention_panel(
        risk_rows=risk_compliance,
        pending_approval=pending_approval,
        processed_bars=processed_bars,
        turnaround_bars=list(avg_processing_sparkline or [0] * 7),
        processed_today=processed_today,
        processed_yesterday=processed_yesterday,
        avg_turnaround_seconds=avg_processing_seconds,
        prior_avg_turnaround_seconds=prior_avg_processing_seconds,
    )

    operations = await build_operations_panel(
        db,
        tenant_id=tenant_id,
        month_start=month_start,
        month_end=month_end,
        today=today,
        actual_processing_minutes=actual_min,
    )
    extraction_quality = await build_extraction_quality(
        db,
        tenant_id=tenant_id,
        month_start=month_start,
        month_end=month_end,
    )
    approval_queue = await build_approval_queue(
        db, tenant_id=tenant_id, base_currency=base_currency
    )
    user_layer = await build_user_layer(
        db,
        tenant_id=tenant_id,
        month_start=month_start,
        month_end=month_end,
        invoices=current,
    )

    return {
        "executive_kpis": executive_kpis,
        "capture_sources": capture_sources,
        "risk_compliance": risk_compliance,
        "attention": attention,
        "operations": operations,
        "extraction_quality": extraction_quality,
        "approval_queue": approval_queue,
        "user_layer": user_layer,
    }
