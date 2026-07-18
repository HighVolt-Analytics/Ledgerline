"""Ingest WhatsApp media attachments into the invoice pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connected_whatsapp import ConnectedWhatsapp
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.services.audit.audit_service import log_event
from app.services.ingest.capture_channel import normalize_phone
from app.services.ingest.canonical_intake_service import (
    build_ingest_source_metadata,
    canonical_intake_enabled_for,
    intake_document,
)
from app.services.ingest.ingest_fanout_service import ingest_file_with_fanout
from app.services.purchase.team_expense_validator import resolve_employee_for_sender
from app.services.master_data.customer_resolver import resolve_capture_slug
from app.services.ingest.whatsapp_graph_client import (
    ParsedWhatsappMessage,
    download_media,
    extension_for_mime,
    mark_message_read,
    send_text_message_with_retry,
)
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
        "We already received this receipt and it is still being processed. "
        "Please wait a moment before sending it again."
    ),
    "duplicate_known": "This receipt was already submitted. No duplicate claim was created.",
    "duplicate_reingest": "Your receipt was resubmitted and is being processed again.",
    "received": "Receipt received — your expense claim is being processed.",
    "received_review": (
        "Receipt received — your expense claim is being processed. "
        "A reviewer may double-check it because matching details were limited."
    ),
}


@dataclass
class WhatsappIngestResult:
    ingested_count: int = 0
    invoice_ids: list[int] | None = None
    skipped_reason: str | None = None

    def __post_init__(self) -> None:
        if self.invoice_ids is None:
            self.invoice_ids = []


def _sender_phone(wa_id: str) -> str:
    digits = normalize_phone(wa_id)
    return f"+{digits}" if digits else wa_id


def _filename_for_message(msg: ParsedWhatsappMessage, ext: str) -> str:
    if msg.filename:
        return msg.filename
    return f"whatsapp-{msg.message_id[:24]}.{ext}"


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


async def _audit_whatsapp_skip(
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
        channel="whatsapp",
        tenant_id=tenant_id,
        message_id=message_id,
        filename=filename,
        exc_type=exc_type,
        extra=extra,
    )


async def ingest_whatsapp_message(
    session: AsyncSession,
    *,
    connection: ConnectedWhatsapp,
    msg: ParsedWhatsappMessage,
    access_token: str,
) -> WhatsappIngestResult:
    result = WhatsappIngestResult()

    if msg.skip_ai:
        await _audit_whatsapp_skip(
            session,
            reason="skipped_message_type",
            tenant_id=connection.tenant_id,
            message_id=msg.message_id,
        )
        result.skipped_reason = "skipped_message_type"
        return result

    org = await session.get(Tenant, connection.tenant_id)
    if not org:
        await _audit_whatsapp_skip(
            session,
            reason="org_not_found",
            tenant_id=connection.tenant_id,
            message_id=msg.message_id,
        )
        result.skipped_reason = "org_not_found"
        return result

    sender = _sender_phone(msg.sender_wa_id)
    employee = await resolve_employee_for_sender(session, connection.tenant_id, sender)

    if msg.msg_type == "text" or (msg.text and not msg.media_id):
        await send_text_message_with_retry(
            connection.phone_number_id,
            access_token=access_token,
            to_wa_id=msg.sender_wa_id,
            text=(
                "Please send a photo or PDF of your receipt so we can process your expense claim."
            ),
        )
        await _audit_whatsapp_skip(
            session,
            reason="text_only",
            tenant_id=connection.tenant_id,
            message_id=msg.message_id,
        )
        result.skipped_reason = "text_only"
        return result

    if not msg.media_id:
        await send_text_message_with_retry(
            connection.phone_number_id,
            access_token=access_token,
            to_wa_id=msg.sender_wa_id,
            text="Unsupported message type. Please send a receipt as a photo or PDF.",
        )
        await _audit_whatsapp_skip(
            session,
            reason="unsupported_type",
            tenant_id=connection.tenant_id,
            message_id=msg.message_id,
        )
        result.skipped_reason = "unsupported_type"
        return result

    if employee is None:
        await send_text_message_with_retry(
            connection.phone_number_id,
            access_token=access_token,
            to_wa_id=msg.sender_wa_id,
            text=(
                "We could not match your number to an employee account. "
                "Ask your admin to register your WhatsApp number in the Rule Book."
            ),
        )
        await log_event(
            session,
            "whatsapp_skipped",
            detail={
                "reason": "unknown_sender",
                "sender": sender,
                "message_id": msg.message_id,
            },
        )
        result.skipped_reason = "unknown_sender"
        return result

    try:
        data, mime_type = await download_media(msg.media_id, access_token=access_token)
    except Exception as exc:
        logger.error(
            "whatsapp_media_download_failed",
            message_id=msg.message_id,
            error=str(exc),
        )
        await send_text_message_with_retry(
            connection.phone_number_id,
            access_token=access_token,
            to_wa_id=msg.sender_wa_id,
            text="We could not download your attachment. Please try sending it again.",
        )
        await _audit_whatsapp_skip(
            session,
            reason="download_failed",
            tenant_id=connection.tenant_id,
            message_id=msg.message_id,
            exc_type=type(exc).__name__,
        )
        result.skipped_reason = "download_failed"
        return result

    if not _mime_allowed(mime_type):
        await send_text_message_with_retry(
            connection.phone_number_id,
            access_token=access_token,
            to_wa_id=msg.sender_wa_id,
            text="Please send your receipt as a PDF, JPG, or PNG file.",
        )
        await _audit_whatsapp_skip(
            session,
            reason="mime_not_allowed",
            tenant_id=connection.tenant_id,
            message_id=msg.message_id,
            extra={"mime_type": mime_type},
        )
        result.skipped_reason = "mime_not_allowed"
        return result

    ext = extension_for_mime(mime_type, msg.filename)
    filename = _filename_for_message(msg, ext)
    caption = (msg.caption or msg.text or "").strip()
    vendor_slug = await resolve_capture_slug(session, sender, tenant_id=connection.tenant_id)
    source = build_ingest_source_metadata(
        capture_source="whatsapp",
        storage_vendor_slug=vendor_slug,
        email_sender=sender,
        email_subject=caption or None,
        email_message_id=msg.message_id,
        email_attachment_name=filename,
        whatsapp_connection_id=connection.id,
        matched_rule_ids=json.dumps(["ingest:whatsapp"]),
    )

    if canonical_intake_enabled_for("whatsapp"):
        outcome = await intake_document(
            session,
            tenant_id=connection.tenant_id,
            tenant_slug=org.slug,
            tenant_name=org.name,
            filename=filename,
            data=data,
            source=source,
            skip_validation=True,
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
            filename=filename,
            data=data,
            source=source,
        )
        action = fanout.action
        review_suggested = fanout.review_suggested

    reply_key = _reply_key_for_action(action, review_suggested=review_suggested)
    await send_text_message_with_retry(
        connection.phone_number_id,
        access_token=access_token,
        to_wa_id=msg.sender_wa_id,
        text=_REPLY_BY_KEY[reply_key],
    )

    if action == "skip_in_progress":
        result.skipped_reason = "duplicate_in_progress"
        return result

    processable_ids: list[int] = []
    for segment_index, invoice_id in enumerate(fanout.invoice_ids):
        inv = await session.get(Invoice, invoice_id)
        if inv is None:
            continue
        if inv.status == InvoiceStatus.DUPLICATE_SKIPPED:
            continue
        processable_ids.append(invoice_id)
        await log_event(
            session,
            "whatsapp_ingested",
            invoice_id=inv.id,
            detail={
                "sender": sender,
                "employee": employee.name,
                "message_id": msg.message_id,
                "filename": filename,
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
        return result

    await mark_message_read(
        connection.phone_number_id,
        access_token=access_token,
        message_id=msg.message_id,
    )

    result.ingested_count = len(processable_ids)
    result.invoice_ids.extend(processable_ids or fanout.invoice_ids)
    return result
