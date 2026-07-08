"""Ingest WhatsApp media attachments into the invoice pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connected_whatsapp import ConnectedWhatsapp
from app.models.invoice import Invoice
from app.models.tenant import Tenant
from app.services.audit.audit_service import log_event
from app.services.ingest.capture_channel import normalize_phone
from app.services.dossier.document_duplicate_service import (
    create_duplicate_shadow_invoice,
    evaluate_file_hash_duplicate,
    find_invoice_by_file_hash,
    log_duplicate_in_progress,
)
from app.services.ingest.ingest_fanout_service import IngestSourceMetadata, ingest_file_with_fanout
from app.services.approval.approval_service import restore_rejected_invoice_file_if_needed
from app.services.invoice.invoice_reset import reset_invoice_for_reprocess
from app.services.purchase.team_expense_validator import resolve_employee_for_sender
from app.services.master_data.customer_resolver import resolve_capture_slug
from app.services.ingest.whatsapp_connection_service import resolve_access_token
from app.services.ingest.whatsapp_graph_client import (
    ParsedWhatsappMessage,
    download_media,
    extension_for_mime,
    mark_message_read,
    send_text_message_with_retry,
)
from app.utils.hashing import compute_sha256_bytes
from app.utils.logger import get_logger

logger = get_logger(__name__)

_ALLOWED_MIME = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
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


async def ingest_whatsapp_message(
    session: AsyncSession,
    *,
    connection: ConnectedWhatsapp,
    msg: ParsedWhatsappMessage,
    access_token: str,
) -> WhatsappIngestResult:
    result = WhatsappIngestResult()

    if msg.skip_ai:
        result.skipped_reason = "skipped_message_type"
        return result

    org = await session.get(Tenant, connection.tenant_id)
    if not org:
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
        result.skipped_reason = "text_only"
        return result

    if not msg.media_id:
        await send_text_message_with_retry(
            connection.phone_number_id,
            access_token=access_token,
            to_wa_id=msg.sender_wa_id,
            text="Unsupported message type. Please send a receipt as a photo or PDF.",
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
        result.skipped_reason = "download_failed"
        return result

    if not _mime_allowed(mime_type):
        await send_text_message_with_retry(
            connection.phone_number_id,
            access_token=access_token,
            to_wa_id=msg.sender_wa_id,
            text="Please send your receipt as a PDF, JPG, or PNG file.",
        )
        result.skipped_reason = "mime_not_allowed"
        return result

    ext = extension_for_mime(mime_type, msg.filename)
    filename = _filename_for_message(msg, ext)
    file_hash = compute_sha256_bytes(data)
    caption = (msg.caption or msg.text or "").strip()

    existing = await find_invoice_by_file_hash(session, file_hash, tenant_id=connection.tenant_id)
    duplicate_decision = evaluate_file_hash_duplicate(existing)
    if duplicate_decision.action == "skip_in_progress":
        await send_text_message_with_retry(
            connection.phone_number_id,
            access_token=access_token,
            to_wa_id=msg.sender_wa_id,
            text=(
                "We already received this receipt and it is still being processed. "
                "Please wait a moment before sending it again."
            ),
        )
        assert existing is not None
        existing.email_message_id = msg.message_id
        await log_duplicate_in_progress(
            session,
            existing,
            detail={
                "filename": filename,
                "message_id": msg.message_id,
                "source": "whatsapp",
            },
        )
        result.skipped_reason = "duplicate_in_progress"
        return result
    if duplicate_decision.action in {"skip_logged", "shadow_duplicate"}:
        assert existing is not None
        if duplicate_decision.action == "shadow_duplicate":
            await create_duplicate_shadow_invoice(
                session,
                tenant_id=connection.tenant_id,
                original=existing,
                whatsapp_connection_id=connection.id,
                email_sender=sender,
                email_subject=caption or None,
                email_attachment_name=filename,
                email_message_id=msg.message_id,
                capture_source="whatsapp",
                file_hash=file_hash,
                extra_detail={
                    "filename": filename,
                    "message_id": msg.message_id,
                    "source": "whatsapp",
                },
            )
        else:
            existing.email_message_id = msg.message_id
            await log_event(
                session,
                "duplicate_skipped",
                invoice_id=existing.id,
                detail={
                    "filename": filename,
                    "message_id": msg.message_id,
                    "source": "whatsapp",
                    "note": "repeat submission ignored",
                },
            )
        await send_text_message_with_retry(
            connection.phone_number_id,
            access_token=access_token,
            to_wa_id=msg.sender_wa_id,
            text="This receipt was already submitted. No duplicate claim was created.",
        )
        result.skipped_reason = "duplicate"
        return result
    if duplicate_decision.action == "reingest_rejected":
        assert existing is not None
        existing.email_sender = sender
        existing.email_subject = caption or None
        existing.email_attachment_name = filename
        existing.email_message_id = msg.message_id
        await restore_rejected_invoice_file_if_needed(session, existing)
        await reset_invoice_for_reprocess(session, existing)
        await log_event(
            session,
            "duplicate_reingest_rejected",
            invoice_id=existing.id,
            detail={
                "filename": filename,
                "message_id": msg.message_id,
                "source": "whatsapp",
            },
        )
        await mark_message_read(
            connection.phone_number_id,
            access_token=access_token,
            message_id=msg.message_id,
        )
        result.ingested_count = 1
        result.invoice_ids.append(existing.id)
        await send_text_message_with_retry(
            connection.phone_number_id,
            access_token=access_token,
            to_wa_id=msg.sender_wa_id,
            text="Your receipt was resubmitted and is being processed again.",
        )
        return result

    vendor_slug = await resolve_capture_slug(session, sender, tenant_id=connection.tenant_id)
    fanout = await ingest_file_with_fanout(
        session,
        tenant_id=connection.tenant_id,
        tenant_slug=org.slug,
        tenant_name=org.name,
        filename=filename,
        data=data,
        source=IngestSourceMetadata(
            storage_vendor_slug=vendor_slug,
            email_sender=sender,
            email_subject=caption or None,
            email_message_id=msg.message_id,
            email_attachment_name=filename,
            whatsapp_connection_id=connection.id,
            capture_source="whatsapp",
            matched_rule_ids=json.dumps(["ingest:whatsapp"]),
        ),
    )

    for segment_index, invoice_id in enumerate(fanout.invoice_ids):
        inv = await session.get(Invoice, invoice_id)
        assert inv is not None
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
            },
        )

    await mark_message_read(
        connection.phone_number_id,
        access_token=access_token,
        message_id=msg.message_id,
    )
    await send_text_message_with_retry(
        connection.phone_number_id,
        access_token=access_token,
        to_wa_id=msg.sender_wa_id,
        text="Receipt received — your expense claim is being processed.",
    )

    result.ingested_count = len(fanout.invoice_ids)
    result.invoice_ids.extend(fanout.invoice_ids)
    return result
