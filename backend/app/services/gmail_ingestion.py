"""Gmail API inbox polling for connected Google mailboxes."""

from __future__ import annotations

import base64
from email.utils import parseaddr

import httpx

from app.config import get_settings
from app.services.email_ingestion import EmailAttachment, RawEmail
from app.services.gmail_oauth_service import gmail_oauth_configured
from app.utils.logger import get_logger

logger = get_logger(__name__)

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


def _gmail_get(path: str, *, access_token: str, params: dict[str, str] | None = None) -> dict:
    url = f"{GMAIL_API}{path}"
    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            params=params or {},
        )
        response.raise_for_status()
        return response.json()


def _decode_gmail_body_data(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _attachments_from_part(
    part: dict,
    *,
    access_token: str,
    message_id: str,
) -> list[EmailAttachment]:
    attachments: list[EmailAttachment] = []
    filename = str(part.get("filename") or "").strip()
    body = part.get("body") if isinstance(part.get("body"), dict) else {}
    attachment_id = body.get("attachmentId") if isinstance(body, dict) else None
    mime_type = str(part.get("mimeType") or "application/octet-stream")

    if filename and attachment_id:
        att_data = _gmail_get(
            f"/messages/{message_id}/attachments/{attachment_id}",
            access_token=access_token,
        )
        raw = att_data.get("data")
        if raw:
            attachments.append(
                EmailAttachment(
                    filename=filename,
                    content_type=mime_type,
                    data=_decode_gmail_body_data(str(raw)),
                )
            )
        return attachments

    for child in part.get("parts") or []:
        if isinstance(child, dict):
            attachments.extend(
                _attachments_from_part(child, access_token=access_token, message_id=message_id)
            )
    return attachments


def _raw_email_from_message(
    mailbox_email: str,
    msg: dict,
    *,
    access_token: str,
) -> RawEmail | None:
    message_id = str(msg.get("id") or "")
    if not message_id:
        return None

    payload = msg.get("payload") if isinstance(msg.get("payload"), dict) else {}
    attachments: list[EmailAttachment] = []
    if payload:
        attachments = _attachments_from_part(payload, access_token=access_token, message_id=message_id)

    subject = ""
    sender = ""
    for header in msg.get("payload", {}).get("headers", []) if isinstance(msg.get("payload"), dict) else []:
        if not isinstance(header, dict):
            continue
        name = str(header.get("name") or "").lower()
        value = str(header.get("value") or "")
        if name == "subject":
            subject = value
        elif name == "from":
            _, sender = parseaddr(value)

    return RawEmail(
        message_id=message_id,
        subject=subject,
        sender=sender,
        mailbox_email=mailbox_email.strip().lower(),
        attachments=attachments,
        graph_access_token=access_token,
    )


def poll_gmail_inbox(mailbox_email: str, *, access_token: str) -> list[RawEmail]:
    if not gmail_oauth_configured():
        logger.info("poll_gmail_skipped", reason="gmail_not_configured")
        return []

    limit = get_settings().graph_max_messages
    list_data = _gmail_get(
        "/messages",
        access_token=access_token,
        params={
            "labelIds": "INBOX",
            "q": "is:unread has:attachment",
            "maxResults": str(limit),
        },
    )
    ids = [str(row.get("id")) for row in list_data.get("messages") or [] if row.get("id")]
    logger.info("poll_gmail_fetched", mailbox=mailbox_email, message_count=len(ids))

    emails: list[RawEmail] = []
    for message_id in ids:
        msg = _gmail_get(
            f"/messages/{message_id}",
            access_token=access_token,
            params={"format": "full"},
        )
        raw = _raw_email_from_message(mailbox_email, msg, access_token=access_token)
        if raw and raw.attachments:
            emails.append(raw)
    return emails
