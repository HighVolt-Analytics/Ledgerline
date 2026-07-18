"""Durable ingest skip/drop audits — alert-ready reason taxonomy."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.audit.audit_service import log_event

ErrorClass = Literal["ops", "filter", "data", "integrity", "failure"]

# Stable reason → alert class (Phase 1 taxonomy; Phase 3 skip_reason reuses these strings).
REASON_ERROR_CLASS: dict[str, ErrorClass] = {
    # ops
    "mailbox_token_failed": "ops",
    "plan_channel_blocked": "ops",
    "mailbox_not_pollable": "ops",
    "graph_not_configured": "ops",
    "gmail_not_configured": "ops",
    "webhook_dedupe_skip": "ops",
    "mailbox_org_missing": "ops",
    "unknown_connection": "ops",
    "token_missing": "ops",
    # filter
    "attachment_type_filtered": "filter",
    "attachment_not_file": "filter",
    "mime_not_allowed": "filter",
    "text_only": "filter",
    "no_invoice_attachments": "filter",
    "no_attachments": "filter",
    "skipped_message_type": "filter",
    "unsupported_type": "filter",
    "not_a_message": "filter",
    "message_already_known": "filter",
    "message_id_missing": "filter",
    "graph_id_missing": "filter",
    # data
    "attachment_bytes_missing": "data",
    "attachment_decode_failed": "data",
    "attachment_record_invalid": "data",
    # integrity
    "ingest_integrity_error": "integrity",
    # failure
    "ingest_message_failed": "failure",
    "mailbox_poll_failed": "failure",
    "download_failed": "failure",
    "org_not_found": "failure",
}

INGEST_SKIPPED_EVENT = "ingest_skipped"


def error_class_for_reason(reason: str) -> ErrorClass:
    return REASON_ERROR_CLASS.get(reason, "failure")


async def log_ingest_skip(
    session: AsyncSession,
    *,
    reason: str,
    channel: str,
    tenant_id: uuid.UUID | int | None = None,
    message_id: str | None = None,
    mailbox: str | None = None,
    filename: str | None = None,
    exc_type: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Write a durable skip/drop audit for future alerting slices."""
    error_class = error_class_for_reason(reason)
    detail: dict[str, Any] = {
        "reason": reason,
        "channel": channel,
        "error_class": error_class,
    }
    if message_id:
        detail["message_id"] = message_id
    if mailbox:
        detail["mailbox"] = mailbox
    if filename:
        detail["filename"] = filename
    if exc_type:
        detail["exc_type"] = exc_type
    if extra:
        detail.update(extra)
    await log_event(
        session,
        INGEST_SKIPPED_EVENT,
        tenant_id=tenant_id,
        detail=detail,
    )
