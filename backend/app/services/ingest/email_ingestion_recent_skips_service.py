"""Recent email_skipped audit rows for mailbox ingestion troubleshooting."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.services.rule_book.rule_book_ingest_stats import format_relative_time

_SKIP_REASON_LABELS: dict[str, str] = {
    "zero_rules_enabled": "no ingestion rules enabled",
    "no_capture_rule_match": "no rule matched",
    "sender_not_employee": "sender not employee",
    "save_attachment_disabled": "save attachment disabled",
    "no_invoice_attachments": "no invoice attachments",
}


def _skip_reason_label(reason: str) -> str:
    token = (reason or "").strip()
    return _SKIP_REASON_LABELS.get(token, token.replace("_", " ") if token else "skipped")


async def load_recent_email_skips_for_mailbox(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    mailbox: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return recent email_skipped audit events for one connected mailbox."""
    mailbox_token = mailbox.strip().lower()
    rows = (
        await session.execute(
            select(AuditLog)
            .where(
                AuditLog.tenant_id == tenant_id,
                AuditLog.event == "email_skipped",
            )
            .order_by(AuditLog.created_at.desc())
            .limit(200)
        )
    ).scalars().all()

    out: list[dict[str, Any]] = []
    for row in rows:
        detail = row.detail if isinstance(row.detail, dict) else {}
        row_mailbox = str(detail.get("mailbox") or "").strip().lower()
        if row_mailbox != mailbox_token:
            continue
        reason = str(detail.get("reason") or "")
        out.append(
            {
                "sender": str(detail.get("sender") or ""),
                "subject": str(detail.get("subject") or ""),
                "attachment": str(detail.get("attachment") or ""),
                "reason": reason,
                "reason_label": _skip_reason_label(reason),
                "timestamp": row.created_at.isoformat() if row.created_at else None,
                "relative_time": format_relative_time(row.created_at),
                "capture_rule_id": detail.get("capture_rule_id"),
                "capture_rule_name": detail.get("capture_rule_name"),
                "message_id": detail.get("message_id"),
            }
        )
        if len(out) >= limit:
            break
    return out
