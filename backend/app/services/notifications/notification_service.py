"""Notification inbox — audit-derived items with per-user read cursor."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.invoice import Invoice
from app.models.user_notification_cursor import UserNotificationCursor
from app.schemas.notifications import (
    MarkNotificationsReadResponse,
    NotificationItem,
    NotificationSeverity,
    NotificationsResponse,
)
from app.services.audit.audit_change_summary import summarize_audit_change
from app.services.credit_service import ensure_tenant_billing

LOW_CREDITS_THRESHOLD = 100
LOW_CREDITS_EVENT = "low_credits"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

_NOTIFICATION_EVENTS = frozenset(
    {
        "pipeline_error",
        "validation_failed",
        "vendor_registration_hold",
        "customer_registration_hold",
        "unmatched_expense_vendor",
        "unmatched_team_vendor",
        "team_expense_approval_required",
        "purchase_awaiting_po",
        "accounting_integration_error",
        "accounting_integration_disconnected",
        "payment_execution_blocked_by_safety_gate",
        "payment_execution_blocked_by_tenant_disable",
        "payment_execution_blocked_by_limit",
        "invoice_processed",
        "invoice_approved",
        "invoice_rejected",
        "duplicate_skipped",
        "duplicate_in_progress",
        "email_ingested",
    }
)

_ACTION_EVENTS = frozenset(
    {
        "validation_failed",
        "vendor_registration_hold",
        "customer_registration_hold",
        "unmatched_expense_vendor",
        "unmatched_team_vendor",
        "team_expense_approval_required",
        "purchase_awaiting_po",
    }
)

_ERROR_EVENTS = frozenset(
    {
        "pipeline_error",
        "accounting_integration_error",
        "accounting_integration_disconnected",
        "payment_execution_blocked_by_safety_gate",
        "payment_execution_blocked_by_tenant_disable",
        "payment_execution_blocked_by_limit",
    }
)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _severity_for_event(event: str) -> NotificationSeverity:
    if event in _ERROR_EVENTS:
        return NotificationSeverity.ERROR
    if event in _ACTION_EVENTS or event == "invoice_rejected":
        return NotificationSeverity.ACTION
    return NotificationSeverity.INFO


def _notification_href(event: str, invoice_id: int | None) -> str | None:
    if event.startswith("accounting_integration_"):
        return "/integrations"
    if event.startswith("payment_execution_blocked_"):
        return "/payments"
    if event == "team_expense_approval_required":
        return "/team-expenses"
    if event == LOW_CREDITS_EVENT:
        return "/billing"
    if event == "email_ingested":
        return "/upload"
    if invoice_id is None:
        return None
    if event in _ACTION_EVENTS or event == "invoice_rejected" or event == "pipeline_error":
        return f"/approvals?invoice={invoice_id}"
    return f"/vault?invoice={invoice_id}"


def _notification_title(
    event: str,
    *,
    document_ref: str | None,
    vendor: str | None,
    summary: str | None,
) -> str:
    if event == LOW_CREDITS_EVENT:
        return "Credits running low"
    ref = (document_ref or "").strip() or "System"
    who = (vendor or "").strip()
    if who:
        base = f"{ref} · {who}"
    else:
        base = ref
    if summary and summary.strip():
        return f"{base} — {summary.strip()}"
    return f"{base} — {event.replace('_', ' ')}"


async def _get_cursor(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: int | None,
) -> datetime:
    row = (
        await db.execute(
            select(UserNotificationCursor).where(
                UserNotificationCursor.tenant_id == tenant_id,
                UserNotificationCursor.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return EPOCH
    return _as_utc(row.last_read_at)


async def _audit_notification_items(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    limit: int,
    last_read_at: datetime,
) -> list[NotificationItem]:
    rows = (
        await db.execute(
            select(AuditLog, Invoice.vendor, Invoice.document_ref)
            .outerjoin(Invoice, Invoice.id == AuditLog.invoice_id)
            .where(
                AuditLog.tenant_id == tenant_id,
                AuditLog.event.in_(_NOTIFICATION_EVENTS),
            )
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
    ).all()

    original_ids: set[int] = set()
    for log, _vendor, _document_ref in rows:
        detail = log.detail if isinstance(log.detail, dict) else {}
        if str(detail.get("original_document_ref") or "").strip():
            continue
        raw_id = detail.get("original_invoice_id")
        if isinstance(raw_id, int):
            original_ids.add(raw_id)

    original_refs: dict[int, tuple[str | None, str | None]] = {}
    if original_ids:
        originals = (
            await db.execute(
                select(Invoice.id, Invoice.document_ref, Invoice.invoice_no).where(
                    Invoice.tenant_id == tenant_id,
                    Invoice.id.in_(original_ids),
                )
            )
        ).all()
        for inv_id, doc_ref, invoice_no in originals:
            original_refs[inv_id] = (
                (doc_ref or "").strip() or None,
                (invoice_no or "").strip() or None,
            )

    items: list[NotificationItem] = []
    for log, vendor, document_ref in rows:
        detail = dict(log.detail) if isinstance(log.detail, dict) else {}
        raw_id = detail.get("original_invoice_id")
        if (
            isinstance(raw_id, int)
            and raw_id in original_refs
            and not str(detail.get("original_document_ref") or "").strip()
        ):
            ref, invoice_no = original_refs[raw_id]
            if ref:
                detail["original_document_ref"] = ref
            if invoice_no and not str(detail.get("original_invoice_no") or "").strip():
                detail["original_invoice_no"] = invoice_no
        ref = (document_ref or "").strip() or None
        if not ref:
            ref = str(detail.get("document_ref") or "").strip() or None
        if not ref:
            # Prefer business invoice number over inventing DOC-{db_id}.
            ref = str(detail.get("invoice_no") or "").strip() or None
        summary = summarize_audit_change(log.event, detail)
        created_at = _as_utc(log.created_at)
        items.append(
            NotificationItem(
                id=f"audit:{log.id}",
                source="audit",
                audit_log_id=log.id,
                event=log.event,
                title=_notification_title(
                    log.event,
                    document_ref=ref,
                    vendor=vendor,
                    summary=summary,
                ),
                summary=summary,
                severity=_severity_for_event(log.event),
                href=_notification_href(log.event, log.invoice_id),
                created_at=created_at,
                is_unread=created_at > last_read_at,
            )
        )
    return items


async def _low_credits_item(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    last_read_at: datetime,
) -> NotificationItem | None:
    billing = await ensure_tenant_billing(db, tenant_id)
    if billing.credit_balance >= LOW_CREDITS_THRESHOLD:
        return None
    created_at = _as_utc(billing.updated_at)
    summary = (
        f"{billing.credit_balance} credits remaining — add credits to avoid processing interruptions"
    )
    return NotificationItem(
        id="system:low_credits",
        source="system",
        audit_log_id=None,
        event=LOW_CREDITS_EVENT,
        title="Credits running low",
        summary=summary,
        severity=NotificationSeverity.ACTION,
        href="/billing",
        created_at=created_at,
        is_unread=created_at > last_read_at,
    )


async def fetch_notifications(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: int | None,
    limit: int = 30,
) -> NotificationsResponse:
    last_read_at = await _get_cursor(db, tenant_id=tenant_id, user_id=user_id)
    audit_items = await _audit_notification_items(
        db,
        tenant_id=tenant_id,
        limit=limit,
        last_read_at=last_read_at,
    )
    low_credits = await _low_credits_item(
        db,
        tenant_id=tenant_id,
        last_read_at=last_read_at,
    )

    items = audit_items
    if low_credits is not None:
        items = [low_credits, *items]
        items = items[:limit]

    unread_count = sum(1 for item in items if item.is_unread)
    cursor_display = None if last_read_at == EPOCH else last_read_at
    return NotificationsResponse(
        items=items,
        unread_count=unread_count,
        last_read_at=cursor_display,
    )


async def mark_notifications_read(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: int | None,
) -> MarkNotificationsReadResponse:
    now = datetime.now(timezone.utc)
    row = (
        await db.execute(
            select(UserNotificationCursor).where(
                UserNotificationCursor.tenant_id == tenant_id,
                UserNotificationCursor.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(
            UserNotificationCursor(
                tenant_id=tenant_id,
                user_id=user_id,
                last_read_at=now,
                updated_at=now,
            )
        )
    else:
        row.last_read_at = now
        row.updated_at = now
    await db.flush()
    return MarkNotificationsReadResponse(unread_count=0)
