"""Gmail API inbox polling for connected Google mailboxes."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.utils import parseaddr

import httpx

from app.config import get_settings
from app.services.ingest.email_ingestion import EmailAttachment, RawEmail, _merge_emails_by_message_id
from app.services.ingest.gmail_oauth_service import gmail_oauth_configured
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


def _gmail_messages_for_query(
    mailbox_email: str,
    *,
    access_token: str,
    query: str,
    known_message_ids: frozenset[str] | None = None,
) -> list[RawEmail]:
    limit = get_settings().graph_max_messages
    list_data = _gmail_get(
        "/messages",
        access_token=access_token,
        params={
            "labelIds": "INBOX",
            "q": query,
            "maxResults": str(limit),
        },
    )
    known = known_message_ids or frozenset()
    ids = [
        str(row.get("id"))
        for row in list_data.get("messages") or []
        if row.get("id") and str(row.get("id")) not in known
    ]

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


def poll_gmail_inbox(
    mailbox_email: str,
    *,
    access_token: str,
    since: datetime | None = None,
    known_message_ids: frozenset[str] | None = None,
) -> list[RawEmail]:
    if not gmail_oauth_configured():
        logger.info("poll_gmail_skipped", reason="gmail_not_configured")
        return []

    unread_emails = _gmail_messages_for_query(
        mailbox_email,
        access_token=access_token,
        query="is:unread has:attachment",
        known_message_ids=known_message_ids,
    )
    recent_emails: list[RawEmail] = []
    if since is not None:
        epoch = int(since.astimezone(timezone.utc).timestamp())
        recent_emails = _gmail_messages_for_query(
            mailbox_email,
            access_token=access_token,
            query=f"has:attachment after:{epoch}",
            known_message_ids=known_message_ids,
        )

    emails = _merge_emails_by_message_id(unread_emails, recent_emails)
    logger.info(
        "poll_gmail_fetched",
        mailbox=mailbox_email,
        message_count=len(emails),
        unread_count=len(unread_emails),
        recent_count=len(recent_emails),
    )
    return emails


def poll_gmail_recent_inbox(
    mailbox_email: str,
    *,
    access_token: str,
    since: datetime,
    known_message_ids: frozenset[str] | None = None,
) -> list[RawEmail]:
    if not gmail_oauth_configured():
        logger.info("poll_gmail_recent_skipped", reason="gmail_not_configured")
        return []

    epoch = int(since.astimezone(timezone.utc).timestamp())
    emails = _gmail_messages_for_query(
        mailbox_email,
        access_token=access_token,
        query=f"has:attachment after:{epoch}",
        known_message_ids=known_message_ids,
    )
    logger.info(
        "poll_gmail_recent_fetched",
        mailbox=mailbox_email,
        message_count=len(emails),
        since=epoch,
    )
    return emails

