"""Ingest Slack media attachments into the invoice pipeline.

Any file shared in a connected workspace is pulled and processed like a manual
upload. No employee-master matching or Team Expenses identity routing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.connected_slack import ConnectedSlackAccount
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.services.audit.audit_service import log_event
from app.services.ingest.canonical_intake_service import (
    build_ingest_source_metadata,
    canonical_intake_enabled_for,
    intake_document,
)
from app.services.ingest.ingest_fanout_service import ingest_file_with_fanout
from app.services.ingest.slack_web_client import (
    ParsedSlackMessage,
    download_private_file,
    extension_for_mime,
    files_info,
    send_message_with_retry,
    users_info,
)
from app.services.master_data.customer_resolver import resolve_capture_slug
from app.utils.logger import get_logger

logger = get_logger(__name__)

_ALLOWED_MIME = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
}

_REPLY_BY_KEY = {
    "duplicate_wait": (
        "We already received this document and it is still being processed. "
        "Please wait a moment before sending it again."
    ),
    "duplicate_known": "This document was already submitted. No duplicate was created.",
    "duplicate_reingest": "Your document was resubmitted and is being processed again.",
    "received": "Document received — we'll process it shortly.",
    "received_review": (
        "Document received — we'll process it shortly. "
        "A reviewer may double-check it because matching details were limited."
    ),
}


@dataclass
class SlackIngestResult:
    ingested_count: int = 0
    invoice_ids: list[int] | None = None
    skipped_reason: str | None = None

    def __post_init__(self) -> None:
        if self.invoice_ids is None:
            self.invoice_ids = []


def _mime_allowed(mime_type: str) -> bool:
    return mime_type.split(";")[0].strip().lower() in _ALLOWED_MIME


def _reply_key_for_action(action: str, *, review_suggested: bool) -> str:
    if action == "skip_in_progress":
        return "duplicate_wait"
    if action in {"shadow_duplicate", "skip_logged"}:
        return "duplicate_known"
    if action == "reingest_rejected":
        return "duplicate_reingest"
    if review_suggested:
        return "received_review"
    return "received"


async def _audit_slack_skip(
    session: AsyncSession,
    *,
    reason: str,
    tenant_id,
    message_id: str | None = None,
    filename: str | None = None,
    exc_type: str | None = None,
    extra: dict | None = None,
) -> None:
    from app.services.ingest.ingest_skip_service import log_ingest_skip

    await log_ingest_skip(
        session,
        reason=reason,
        channel="slack",
        tenant_id=tenant_id,
        message_id=message_id,
        filename=filename,
        exc_type=exc_type,
        extra=extra,
    )


async def _reply(
    access_token: str,
    msg: ParsedSlackMessage,
    text: str,
) -> None:
    await send_message_with_retry(
        access_token,
        channel=msg.channel,
        text=text,
        thread_ts=msg.thread_ts or msg.ts,
    )


async def resolve_slack_sender_label(
    *,
    access_token: str,
    slack_user_id: str,
) -> str:
    """Best-effort display label for audit; never blocks ingest."""
    fallback = f"slack:{slack_user_id}"
    if not slack_user_id:
        return fallback
    try:
        info = await users_info(access_token, slack_user_id)
    except Exception as exc:
        logger.warning(
            "slack_users_info_failed",
            user_id=slack_user_id,
            error=str(exc),
        )
        return fallback

    user = info.get("user") if isinstance(info.get("user"), dict) else {}
    profile = user.get("profile") if isinstance(user.get("profile"), dict) else {}
    email = str(profile.get("email") or "").strip()
    if email:
        return email
    name = str(
        profile.get("real_name")
        or profile.get("display_name")
        or user.get("name")
        or ""
    ).strip()
    if name:
        return name
    return fallback


async def ingest_slack_message(
    session: AsyncSession,
    *,
    connection: ConnectedSlackAccount,
    msg: ParsedSlackMessage,
    access_token: str,
) -> SlackIngestResult:
    result = SlackIngestResult()

    if msg.skip_ai:
        await _audit_slack_skip(
            session,
            reason="skipped_message_type",
            tenant_id=connection.tenant_id,
            message_id=msg.event_id,
        )
        result.skipped_reason = "skipped_message_type"
        return result

    org = await session.get(Tenant, connection.tenant_id)
    if not org:
        await _audit_slack_skip(
            session,
            reason="org_not_found",
            tenant_id=connection.tenant_id,
            message_id=msg.event_id,
        )
        result.skipped_reason = "org_not_found"
        return result

    # Upload-like intake: anyone in the connected workspace. No employee-master gate.
    sender_label = await resolve_slack_sender_label(
        access_token=access_token,
        slack_user_id=msg.user_id,
    )

    if not msg.files:
        await _reply(
            access_token,
            msg,
            "Please send a photo or PDF of the document so we can process it.",
        )
        await _audit_slack_skip(
            session,
            reason="text_only",
            tenant_id=connection.tenant_id,
            message_id=msg.event_id,
        )
        result.skipped_reason = "text_only"
        return result

    max_bytes = get_settings().max_upload_file_bytes
    processable_ids: list[int] = []
    last_action = "allow"
    last_review = False
    any_ingested = False

    for file_ref in msg.files:
        mime_type = (file_ref.mimetype or "").strip()
        url_private = file_ref.url_private
        filename = file_ref.name
        file_size = file_ref.size

        # Refresh metadata when message payload lacks url_private / mimetype
        if not url_private or not mime_type:
            try:
                meta = await files_info(access_token, file_ref.file_id)
                file_obj = meta.get("file") if isinstance(meta.get("file"), dict) else {}
                url_private = (
                    str(file_obj.get("url_private_download") or file_obj.get("url_private") or "")
                    or url_private
                )
                mime_type = str(file_obj.get("mimetype") or mime_type or "")
                filename = filename or str(file_obj.get("name") or "") or None
                if file_size is None and file_obj.get("size") is not None:
                    try:
                        file_size = int(file_obj["size"])
                    except (TypeError, ValueError):
                        pass
            except Exception as exc:
                logger.error(
                    "slack_files_info_failed",
                    file_id=file_ref.file_id,
                    error=str(exc),
                )
                await _reply(
                    access_token,
                    msg,
                    "We could not download your attachment. Please try sending it again.",
                )
                await _audit_slack_skip(
                    session,
                    reason="download_failed",
                    tenant_id=connection.tenant_id,
                    message_id=msg.event_id,
                    exc_type=type(exc).__name__,
                )
                result.skipped_reason = "download_failed"
                continue

        if file_size is not None and file_size > max_bytes:
            await _reply(
                access_token,
                msg,
                f"That file is too large (max {max_bytes // (1024 * 1024)} MB). "
                "Please send a smaller PDF or image.",
            )
            await _audit_slack_skip(
                session,
                reason="file_too_large",
                tenant_id=connection.tenant_id,
                message_id=msg.event_id,
                filename=filename,
                extra={"size": file_size, "max_bytes": max_bytes},
            )
            result.skipped_reason = "file_too_large"
            continue

        if not mime_type or not _mime_allowed(mime_type):
            await _reply(
                access_token,
                msg,
                "Please send your document as a PDF, JPG, or PNG file.",
            )
            await _audit_slack_skip(
                session,
                reason="mime_not_allowed",
                tenant_id=connection.tenant_id,
                message_id=msg.event_id,
                filename=filename,
                extra={"mime_type": mime_type},
            )
            result.skipped_reason = "mime_not_allowed"
            continue

        if not url_private:
            await _reply(
                access_token,
                msg,
                "We could not download your attachment. Please try sending it again.",
            )
            await _audit_slack_skip(
                session,
                reason="download_failed",
                tenant_id=connection.tenant_id,
                message_id=msg.event_id,
                filename=filename,
            )
            result.skipped_reason = "download_failed"
            continue

        try:
            data = await download_private_file(url_private, access_token=access_token)
        except Exception as exc:
            logger.error(
                "slack_file_download_failed",
                file_id=file_ref.file_id,
                error=str(exc),
            )
            await _reply(
                access_token,
                msg,
                "We could not download your attachment. Please try sending it again.",
            )
            await _audit_slack_skip(
                session,
                reason="download_failed",
                tenant_id=connection.tenant_id,
                message_id=msg.event_id,
                filename=filename,
                exc_type=type(exc).__name__,
            )
            result.skipped_reason = "download_failed"
            continue

        if len(data) > max_bytes:
            await _reply(
                access_token,
                msg,
                f"That file is too large (max {max_bytes // (1024 * 1024)} MB). "
                "Please send a smaller PDF or image.",
            )
            await _audit_slack_skip(
                session,
                reason="file_too_large",
                tenant_id=connection.tenant_id,
                message_id=msg.event_id,
                filename=filename,
                extra={"size": len(data), "max_bytes": max_bytes},
            )
            result.skipped_reason = "file_too_large"
            continue

        ext = extension_for_mime(mime_type, filename)
        safe_name = filename or f"slack-{msg.event_id[:24]}.{ext}"
        caption = (msg.text or "").strip()
        vendor_slug = await resolve_capture_slug(
            session, sender_label, tenant_id=connection.tenant_id
        )
        source = build_ingest_source_metadata(
            capture_source="slack",
            storage_vendor_slug=vendor_slug,
            email_sender=sender_label,
            email_subject=caption or None,
            email_message_id=msg.ts or msg.event_id,
            email_attachment_name=safe_name,
            slack_connection_id=connection.id,
            matched_rule_ids=json.dumps(["ingest:slack"]),
        )

        # Same intake path as manual upload (filename validation on).
        if canonical_intake_enabled_for("slack"):
            outcome = await intake_document(
                session,
                tenant_id=connection.tenant_id,
                tenant_slug=org.slug,
                tenant_name=org.name,
                filename=safe_name,
                data=data,
                source=source,
                skip_validation=False,
            )
            fanout = outcome.result
            action = outcome.action
            review_suggested = outcome.review_suggested
        else:
            fanout = await ingest_file_with_fanout(
                session,
                tenant_id=connection.tenant_id,
                tenant_slug=org.slug,
                tenant_name=org.name,
                filename=safe_name,
                data=data,
                source=source,
            )
            action = fanout.action
            review_suggested = fanout.review_suggested

        last_action = action
        last_review = review_suggested
        any_ingested = True

        for segment_index, invoice_id in enumerate(fanout.invoice_ids):
            inv = await session.get(Invoice, invoice_id)
            if inv is None:
                continue
            if inv.status == InvoiceStatus.DUPLICATE_SKIPPED:
                continue
            processable_ids.append(invoice_id)
            await log_event(
                session,
                "slack_ingested",
                invoice_id=inv.id,
                detail={
                    "sender": sender_label,
                    "slack_user_id": msg.user_id,
                    "event_id": msg.event_id,
                    "filename": safe_name,
                    "storage": inv.raw_file_path,
                    "parent_file_hash": fanout.parent_file_hash,
                    "segment_index": segment_index,
                    "segment_count": fanout.segment_count,
                    "action": action,
                },
            )

        if action in {"shadow_duplicate", "skip_logged"} and not processable_ids:
            result.skipped_reason = "duplicate"
            result.invoice_ids.extend(fanout.invoice_ids)

    if any_ingested:
        reply_key = _reply_key_for_action(last_action, review_suggested=last_review)
        await _reply(access_token, msg, _REPLY_BY_KEY[reply_key])

    if last_action == "skip_in_progress":
        result.skipped_reason = "duplicate_in_progress"
        return result

    result.ingested_count = len(processable_ids)
    result.invoice_ids.extend(processable_ids)
    return result
