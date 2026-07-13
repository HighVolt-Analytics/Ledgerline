"""Probe vishnu@highvolt.tech inbox vs Exceptions folder."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

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
    async with async_session_factory() as session:
        mb = (
            await session.execute(
                select(ConnectedMailbox).where(ConnectedMailbox.email == "vishnu@highvolt.tech")
            )
        ).scalars().first()
        if not mb:
            print("mailbox not found")
            return

        print("tenant_id", mb.tenant_id, "mailbox_id", mb.id)
        token = await resolve_mailbox_access_token(session, mb)
        since = datetime.now(timezone.utc) - timedelta(hours=48)

        unread = _list_unread_messages(mb.email, access_token=token)
        recent = _list_recent_messages(mb.email, access_token=token, since=since)
        print("INBOX unread:", len(unread), "recent:", len(recent))
        for msg in unread + recent:
            print("  inbox", msg.get("receivedDateTime"), msg.get("subject"), str(msg.get("id", ""))[:40])

        children = graph_request(
            "GET",
            mailbox_api_path(mb.email, "/mailFolders/inbox/childFolders"),
            access_token=token,
        )
        exc_id = None
        for folder in children.get("value", []):
            name = folder.get("displayName")
            print(
                f"folder {name}: total={folder.get('totalItemCount')} "
                f"unread={folder.get('unreadItemCount')}"
            )
            if name == "Exceptions":
                exc_id = folder.get("id")

        if exc_id:
            exc = graph_request(
                "GET",
                mailbox_api_path(mb.email, f"/mailFolders/{exc_id}/messages"),
                params={
                    "$filter": "hasAttachments eq true",
                    "$top": "15",
                    "$select": "id,subject,from,receivedDateTime,isRead",
                },
                access_token=token,
            )
            print("EXCEPTIONS with attachments:", len(exc.get("value", [])))
            for msg in exc.get("value", []):
                frm = (msg.get("from") or {}).get("emailAddress", {})
                print(
                    "  exc",
                    msg.get("receivedDateTime"),
                    msg.get("subject"),
                    frm.get("address"),
                    str(msg.get("id", ""))[:40],
                )

        from app.services.ingest.email_ingestion import poll_inbox

        polled = poll_inbox(mb.email, access_token=token, since=since)
        print("poll_inbox result:", len(polled))
        for email in polled[:5]:
            print(" polled", email.subject, email.sender, email.message_id[:40])

        if exc_id:
            today = graph_request(
                "GET",
                mailbox_api_path(mb.email, f"/mailFolders/{exc_id}/messages"),
                params={
                    "$filter": "receivedDateTime ge 2026-07-13T00:00:00Z and hasAttachments eq true",
                    "$select": "id,subject,from,receivedDateTime,isRead",
                    "$top": "10",
                },
                access_token=token,
            )
            print("TODAY exceptions:", len(today.get("value", [])))
            for msg in today.get("value", []):
                frm = (msg.get("from") or {}).get("emailAddress", {})
                print(
                    "  today",
                    msg.get("receivedDateTime"),
                    msg.get("subject"),
                    frm.get("address"),
                    frm.get("name"),
                )


if __name__ == "__main__":
    asyncio.run(main())
