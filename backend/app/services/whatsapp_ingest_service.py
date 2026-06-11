"""Ingest WhatsApp media attachments into the invoice pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connected_whatsapp import ConnectedWhatsapp
from app.models.invoice import Invoice, InvoiceStatus
from app.models.organisation import Organisation
from app.services.audit_service import log_event
from app.services.capture_channel import normalize_phone
from app.services.file_storage import store_invoice_pdf
from app.utils.hashing import compute_sha256_bytes
from app.services.invoice_evaluation_service import EVAL_NEEDS_REVIEW, ROUTE_TEAM
from app.services.pipeline import find_by_hash
from app.services.team_expense_validator import resolve_employee_for_sender
from app.services.vendor_resolver import resolve_vendor_slug
from app.services.whatsapp_connection_service import resolve_access_token
from app.services.whatsapp_graph_client import (
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

    org = await session.get(Organisation, connection.org_id)
    if not org:
        result.skipped_reason = "org_not_found"
        return result

    sender = _sender_phone(msg.sender_wa_id)
    employee = await resolve_employee_for_sender(session, connection.org_id, sender)

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

    existing = await find_by_hash(session, file_hash, org_id=connection.org_id)
    if existing:
        if existing.status != InvoiceStatus.PROCESSED:
            result.skipped_reason = "duplicate_in_progress"
            return result
        existing.status = InvoiceStatus.DUPLICATE_SKIPPED
        existing.email_message_id = msg.message_id
        await log_event(
            session,
            "duplicate_skipped",
            invoice_id=existing.id,
            detail={"filename": filename, "message_id": msg.message_id, "source": "whatsapp"},
        )
        await send_text_message_with_retry(
            connection.phone_number_id,
            access_token=access_token,
            to_wa_id=msg.sender_wa_id,
            text="This receipt was already submitted. No duplicate claim was created.",
        )
        result.skipped_reason = "duplicate"
        return result

    vendor_slug = await resolve_vendor_slug(session, sender, org_id=connection.org_id)
    caption = (msg.caption or msg.text or "").strip()
    inv = Invoice(
        org_id=connection.org_id,
        whatsapp_connection_id=connection.id,
        status=InvoiceStatus.PENDING,
        file_hash=file_hash,
        currency="AUD",
        email_sender=sender,
        email_subject=caption or None,
        email_attachment_name=filename,
        email_message_id=msg.message_id,
        storage_vendor_slug=vendor_slug,
        route_target=ROUTE_TEAM,
        capture_source="whatsapp",
        evaluation_status=EVAL_NEEDS_REVIEW,
        matched_rule_ids=json.dumps(["whatsapp:team_expense"]),
    )
    session.add(inv)
    await session.flush()

    stored = store_invoice_pdf(
        data,
        org.slug,
        vendor_slug,
        inv.id,
        file_hash,
        filename,
        org_name=org.name,
        route_target=ROUTE_TEAM,
    )
    inv.raw_file_path = stored

    await log_event(
        session,
        "whatsapp_ingested",
        invoice_id=inv.id,
        detail={
            "sender": sender,
            "employee": employee.name,
            "message_id": msg.message_id,
            "filename": filename,
            "storage": stored,
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

    result.ingested_count = 1
    result.invoice_ids.append(inv.id)
    return result
