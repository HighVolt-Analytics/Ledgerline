"""Runtime email-capture ingest stats from audit_logs.

Matched counts are derived at read time — never written into rule book config.
This keeps config immutable under ingest traffic and gives correct calendar-month totals.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog

INGEST_CAPTURE_EVENT = "ingest_capture_matched"


@dataclass(frozen=True, slots=True)
class EmailCaptureIngestStats:
    matched_count: int
    last_matched: str


def month_start_utc(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def format_relative_time(at: datetime | None, *, now: datetime | None = None) -> str:
    if at is None:
        return "—"
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    diff = reference - at
    mins = int(diff.total_seconds() // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins}m ago"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs}h ago"
    return f"{hrs // 24}d ago"


async def load_email_capture_ingest_stats(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> dict[str, EmailCaptureIngestStats]:
    """Aggregate ingest_capture_matched audit rows per rule id."""
    month_start = month_start_utc(now)
    rule_id_expr = AuditLog.detail["rule_id"].as_string()
    rows = (
        await session.execute(
            select(
                rule_id_expr.label("rule_id"),
                func.coalesce(
                    func.sum(case((AuditLog.created_at >= month_start, 1), else_=0)),
                    0,
                ).label("month_count"),
                func.max(AuditLog.created_at).label("last_at"),
            )
            .where(
                AuditLog.tenant_id == tenant_id,
                AuditLog.event == INGEST_CAPTURE_EVENT,
            )
            .group_by(rule_id_expr)
        )
    ).all()

    stats: dict[str, EmailCaptureIngestStats] = {}
    for rule_id, month_count, last_at in rows:
        token = str(rule_id or "").strip()
        if not token:
            continue
        created = last_at
        if created is not None and getattr(created, "tzinfo", None) is None:
            created = created.replace(tzinfo=timezone.utc)
        stats[token] = EmailCaptureIngestStats(
            matched_count=int(month_count or 0),
            last_matched=format_relative_time(created, now=now),
        )
    return stats


def strip_email_capture_volatile_stats(data: dict[str, Any]) -> dict[str, Any]:
    """Remove server-owned stats before persisting rule book config."""
    rules = data.get("email_capture_rules")
    if not isinstance(rules, list):
        return data
    for rule in rules:
        if isinstance(rule, dict):
            rule.pop("matched_count", None)
            rule.pop("last_matched", None)
    return data


async def attach_email_capture_ingest_stats(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    config: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Overlay matched_count / last_matched on email_capture_rules for API responses."""
    rules = config.get("email_capture_rules")
    if not isinstance(rules, list) or not rules:
        return config

    stats = await load_email_capture_ingest_stats(session, tenant_id, now=now)
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rule_id = str(rule.get("id") or "").strip()
        row = stats.get(rule_id)
        rule["matched_count"] = row.matched_count if row else 0
        rule["last_matched"] = row.last_matched if row else "—"
    return config
