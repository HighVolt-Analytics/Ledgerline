"""Inbox polling via Microsoft Graph."""

import base64
from dataclasses import dataclass, field
from pathlib import Path

from app.config import get_settings
from app.services.graph_client import graph_request, is_graph_enabled
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class EmailAttachment:
    filename: str
    content_type: str
    data: bytes


@dataclass
class RawEmail:
    message_id: str
    subject: str
    sender: str
    mailbox_email: str
    attachments: list[EmailAttachment] = field(default_factory=list)
    graph_access_token: str | None = None


def mailbox_api_path(mailbox_email: str, segment: str) -> str:
    mailbox = mailbox_email.strip()
    return f"/users/{mailbox}{segment}"


def _list_unread_messages(mailbox_email: str, *, access_token: str | None = None) -> list[dict[str, object]]:
    """Fetch unread inbox messages that have attachments."""
    limit = get_settings().graph_max_messages
    params = {
        "$filter": "isRead eq false and hasAttachments eq true",
        "$select": "id,subject,from,hasAttachments,receivedDateTime",
        "$top": str(limit),
    }
    data = graph_request(
        "GET",
        mailbox_api_path(mailbox_email, "/mailFolders/inbox/messages"),
        params=params,
        access_token=access_token,
    )
    return data.get("value", [])  # type: ignore[return-value]


def _list_attachments(
    mailbox_email: str,
    message_id: str,
    *,
    access_token: str | None = None,
) -> list[dict[str, object]]:
    data = graph_request(
        "GET",
        mailbox_api_path(mailbox_email, f"/messages/{message_id}/attachments"),
        access_token=access_token,
    )
    return data.get("value", [])  # type: ignore[return-value]


def _decode_attachment(record: dict[str, object]) -> EmailAttachment | None:
    odata_type = record.get("@odata.type", "")
    if odata_type != "#microsoft.graph.fileAttachment":
        return None

    name = str(record.get("name") or "attachment.bin")
    content_type = str(record.get("contentType") or "application/octet-stream")
    raw = record.get("contentBytes")
    if not raw:
        return None

    try:
        data = base64.b64decode(str(raw))
    except (ValueError, TypeError):
        logger.warning("attachment_decode_failed", filename=name)
        return None

    return EmailAttachment(filename=name, content_type=content_type, data=data)


def poll_inbox(mailbox_email: str, *, access_token: str | None = None) -> list[RawEmail]:
    """
    Poll a mailbox for unread messages with attachments.

    Returns empty list when Graph is not configured (local dev without Azure).
    """
    if not is_graph_enabled():
        logger.info("poll_inbox_skipped", reason="graph_not_configured")
        return []

    mailbox = mailbox_email.strip().lower()
    emails: list[RawEmail] = []
    messages = _list_unread_messages(mailbox, access_token=access_token)
    logger.info("poll_inbox_fetched", mailbox=mailbox, message_count=len(messages))

    for msg in messages:
        message_id = str(msg.get("id", ""))
        if not message_id:
            continue

        sender = ""
        from_block = msg.get("from")
        if isinstance(from_block, dict):
            addr = from_block.get("emailAddress")
            if isinstance(addr, dict):
                sender = str(addr.get("address") or "")

        attachments: list[EmailAttachment] = []
        for record in _list_attachments(mailbox, message_id, access_token=access_token):
            if not isinstance(record, dict):
                continue
            att = _decode_attachment(record)
            if att:
                attachments.append(att)

        emails.append(
            RawEmail(
                message_id=message_id,
                subject=str(msg.get("subject") or ""),
                sender=sender,
                mailbox_email=mailbox,
                attachments=attachments,
                graph_access_token=access_token,
            )
        )

    return emails


def mark_message_read(
    message_id: str,
    mailbox_email: str,
    *,
    access_token: str | None = None,
) -> bool:
    """
    Mark a message as read after processing.

    Requires Graph application permission Mail.ReadWrite.
    Returns False on 403 so ingestion still completes if only Mail.Read is granted.
    """
    if not is_graph_enabled():
        return False
    try:
        graph_request(
            "PATCH",
            mailbox_api_path(mailbox_email, f"/messages/{message_id}"),
            json_body={"isRead": True},
            access_token=access_token,
        )
        logger.info("message_marked_read", message_id=message_id, mailbox=mailbox_email)
        return True
    except Exception as exc:
        logger.warning(
            "message_mark_read_failed",
            message_id=message_id,
            mailbox=mailbox_email,
            error=str(exc),
            hint="Add Mail.ReadWrite application permission and grant admin consent",
        )
        return False


def save_attachment(attachment: EmailAttachment, upload_dir: Path) -> Path:
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / Path(attachment.filename).name
    n = 0
    while dest.exists():
        n += 1
        dest = upload_dir / f"{dest.stem}_{n}{dest.suffix}"
    dest.write_bytes(attachment.data)
    return dest
