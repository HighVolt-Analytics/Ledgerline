"""Inbox polling via Microsoft Graph."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
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


def _graph_datetime(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _date_range_bounds(from_day: date, to_day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(from_day, time.min, tzinfo=timezone.utc)
    end = datetime.combine(to_day + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return start, end


def build_historical_inbox_filter(from_day: date, to_day: date) -> str:
    """Graph filter for date-range import (read + unread, with attachments)."""
    start, end = _date_range_bounds(from_day, to_day)
    return (
        f"receivedDateTime ge {_graph_datetime(start)} and "
        f"receivedDateTime lt {_graph_datetime(end)} and "
        f"hasAttachments eq true"
    )


def _list_inbox_message_pages(
    mailbox_email: str,
    *,
    access_token: str | None,
    odata_filter: str,
    page_size: int,
    max_messages: int | None = None,
) -> Iterator[list[dict[str, object]]]:
    """Yield inbox message pages from Graph, following @odata.nextLink."""
    if not is_graph_enabled():
        return

    mailbox = mailbox_email.strip().lower()
    path = mailbox_api_path(mailbox, "/mailFolders/inbox/messages")
    params: dict[str, str] | None = {
        "$filter": odata_filter,
        "$select": "id,subject,from,hasAttachments,receivedDateTime",
        "$top": str(page_size),
    }
    next_url: str | None = None
    fetched = 0

    while True:
        if next_url:
            data = graph_request("GET", next_url, access_token=access_token)
        else:
            data = graph_request("GET", path, params=params, access_token=access_token)

        batch = data.get("value", [])
        if not isinstance(batch, list) or not batch:
            break

        if max_messages is not None:
            remaining = max_messages - fetched
            if remaining <= 0:
                break
            if len(batch) > remaining:
                batch = batch[:remaining]

        yield batch  # type: ignore[misc]
        fetched += len(batch)

        if max_messages is not None and fetched >= max_messages:
            break

        next_link = data.get("@odata.nextLink")
        if not isinstance(next_link, str) or not next_link.strip():
            break
        next_url = next_link
        params = None


def _list_unread_messages(mailbox_email: str, *, access_token: str | None = None) -> list[dict[str, object]]:
    """Fetch unread inbox messages that have attachments."""
    limit = get_settings().graph_max_messages
    rows: list[dict[str, object]] = []
    for page in _list_inbox_message_pages(
        mailbox_email,
        access_token=access_token,
        odata_filter="isRead eq false and hasAttachments eq true",
        page_size=limit,
        max_messages=limit,
    ):
        rows.extend(page)
    return rows


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


def _sender_from_message(msg: dict[str, object]) -> str:
    from_block = msg.get("from")
    if isinstance(from_block, dict):
        addr = from_block.get("emailAddress")
        if isinstance(addr, dict):
            return str(addr.get("address") or "")
    return ""


def _raw_email_from_message(
    mailbox_email: str,
    msg: dict[str, object],
    *,
    access_token: str | None = None,
) -> RawEmail | None:
    message_id = str(msg.get("id", ""))
    if not message_id:
        return None

    attachments: list[EmailAttachment] = []
    for record in _list_attachments(mailbox_email, message_id, access_token=access_token):
        if not isinstance(record, dict):
            continue
        att = _decode_attachment(record)
        if att:
            attachments.append(att)

    return RawEmail(
        message_id=message_id,
        subject=str(msg.get("subject") or ""),
        sender=_sender_from_message(msg),
        mailbox_email=mailbox_email.strip().lower(),
        attachments=attachments,
        graph_access_token=access_token,
    )


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
        raw = _raw_email_from_message(mailbox, msg, access_token=access_token)
        if raw:
            emails.append(raw)

    return emails


def fetch_historical_inbox(
    mailbox_email: str,
    *,
    from_day: date,
    to_day: date,
    access_token: str | None = None,
    max_messages: int | None = None,
) -> list[RawEmail]:
    """Fetch inbox messages with attachments in [from_day, to_day] (inclusive)."""
    if not is_graph_enabled():
        logger.info("historical_inbox_skipped", reason="graph_not_configured")
        return []

    mailbox = mailbox_email.strip().lower()
    limit = max_messages if max_messages is not None else get_settings().graph_backfill_max_messages
    odata_filter = build_historical_inbox_filter(from_day, to_day)
    emails: list[RawEmail] = []

    for page in _list_inbox_message_pages(
        mailbox,
        access_token=access_token,
        odata_filter=odata_filter,
        page_size=min(get_settings().graph_max_messages, 50),
        max_messages=limit,
    ):
        for msg in page:
            raw = _raw_email_from_message(mailbox, msg, access_token=access_token)
            if raw:
                emails.append(raw)

    logger.info(
        "historical_inbox_fetched",
        mailbox=mailbox,
        message_count=len(emails),
        from_date=str(from_day),
        to_date=str(to_day),
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
