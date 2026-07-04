"""Dispatch inbox polling to Microsoft Graph or Gmail API."""

from __future__ import annotations

from datetime import datetime

from app.models.connected_mailbox import MAIL_PROVIDER_GOOGLE
from app.services.ingest.email_ingestion import RawEmail, poll_inbox
from app.services.ingest.gmail_ingestion import poll_gmail_inbox


def poll_connected_mailbox(
    mailbox_email: str,
    *,
    access_token: str,
    mail_provider: str,
    since: datetime | None = None,
    known_message_ids: frozenset[str] | None = None,
) -> list[RawEmail]:
    if mail_provider == MAIL_PROVIDER_GOOGLE:
        return poll_gmail_inbox(
            mailbox_email,
            access_token=access_token,
            since=since,
            known_message_ids=known_message_ids,
        )
    return poll_inbox(
        mailbox_email,
        access_token=access_token,
        since=since,
        known_message_ids=known_message_ids,
    )
