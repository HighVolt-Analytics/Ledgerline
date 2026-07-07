"""Probe connected mailboxes against Microsoft Graph inbox."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_factory
from app.models.connected_mailbox import ConnectedMailbox
from app.services.ingest.email_ingestion import (
    _list_recent_messages,
    _list_unread_messages,
    mailbox_api_path,
)
from app.services.ingest.graph_client import graph_request
from app.services.ingest.mailbox_oauth_service import resolve_mailbox_access_token


async def main() -> None:
    settings = get_settings()
    print("graph_mailbox:", repr(settings.graph_mailbox))
    print("graph_enabled:", settings.graph_enabled)

    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(ConnectedMailbox).where(ConnectedMailbox.is_active.is_(True))
            )
        ).scalars().all()
        for mb in rows:
            print(f"\n=== {mb.email} (id={mb.id}, auth={mb.auth_type}) ===")
            print(
                "status:",
                mb.connection_status,
                "refresh:",
                bool(mb.refresh_token_encrypted),
                "last_error:",
                mb.last_error,
            )
            try:
                token = await resolve_mailbox_access_token(session, mb)
                print("token ok, len", len(token))
            except Exception as exc:
                print("TOKEN ERROR:", exc)
                continue

            since = datetime.now(timezone.utc) - timedelta(hours=48)
            unread = _list_unread_messages(mb.email, access_token=token)
            recent = _list_recent_messages(mb.email, access_token=token, since=since)
            print("unread with attachments:", len(unread))
            print("recent with attachments (48h):", len(recent))

            data = graph_request(
                "GET",
                mailbox_api_path(mb.email, "/mailFolders/inbox/messages"),
                params={
                    "$top": "5",
                    "$select": "id,subject,hasAttachments,isRead,receivedDateTime",
                },
                access_token=token,
            )
            for msg in data.get("value", []):
                print(
                    " ",
                    msg.get("subject"),
                    "| attachments:",
                    msg.get("hasAttachments"),
                    "| read:",
                    msg.get("isRead"),
                    "|",
                    msg.get("receivedDateTime"),
                )

            attached = graph_request(
                "GET",
                mailbox_api_path(mb.email, "/mailFolders/inbox/messages"),
                params={
                    "$filter": "hasAttachments eq true",
                    "$top": "10",
                    "$select": "id,subject,receivedDateTime",
                },
                access_token=token,
            )
            attached_msgs = attached.get("value", [])
            print("all-time inbox with attachments:", len(attached_msgs))
            for msg in attached_msgs:
                print("  [att]", msg.get("subject"), msg.get("receivedDateTime"))


if __name__ == "__main__":
    asyncio.run(main())
