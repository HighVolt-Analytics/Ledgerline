"""Dry-run preview: evaluate a draft capture rule against recent mailbox mail."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connected_mailbox import ConnectedMailbox
from app.schemas.rule_book_config import EmailCaptureAction, EmailCaptureRule, RuleConditionGroup
from app.services.ingest.attachment_filter import filter_invoice_attachments
from app.services.ingest.email_ingestion import poll_recent_inbox
from app.services.ingest.ingest_capture_service import raw_email_to_sample_email
from app.services.ingest.mailbox_oauth_service import resolve_mailbox_access_token
from app.services.rule_book.rule_engine import match_email_capture_rule


async def preview_email_capture_rule(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    mailbox: str,
    root: RuleConditionGroup,
    lookback_days: int = 30,
    rule_name: str = "Preview rule",
) -> dict[str, object]:
    """Fetch recent mailbox messages and report attachments that would match the draft rule."""
    mailbox_email = mailbox.strip().lower()
    mb = (
        await session.execute(
            select(ConnectedMailbox).where(
                ConnectedMailbox.tenant_id == tenant_id,
                ConnectedMailbox.email == mailbox_email,
                ConnectedMailbox.is_active.is_(True),
            )
        )
    ).scalars().first()
    if mb is None:
        return {
            "mailbox": mailbox_email,
            "lookback_days": lookback_days,
            "message_count": 0,
            "matches": [],
            "warnings": [f"No active connected mailbox found for {mailbox_email}."],
        }

    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(lookback_days, 90)))
    access_token = await resolve_mailbox_access_token(session, mb)
    emails = poll_recent_inbox(
        mailbox_email,
        access_token=access_token,
        since=since,
        known_message_ids=None,
    )

    draft = EmailCaptureRule(
        id="preview",
        name=rule_name,
        enabled=True,
        priority=1,
        mailbox=mailbox_email if mailbox_email else "*",
        root=root,
        action=EmailCaptureAction(save_attachment=True, route_to="Purchase Management", tags=[]),
    )

    matches: list[dict[str, object]] = []
    for email in emails:
        for att in filter_invoice_attachments(email):
            sample = raw_email_to_sample_email(email, att)
            hit = match_email_capture_rule(
                sample,
                [draft],
                mailbox=email.mailbox_email,
            )
            if hit is None:
                continue
            matches.append(
                {
                    "message_id": email.message_id,
                    "subject": email.subject,
                    "sender": email.sender,
                    "attachment": att.filename,
                    "received_at": email.received_at.isoformat() if email.received_at else None,
                }
            )

    return {
        "mailbox": mailbox_email,
        "lookback_days": lookback_days,
        "message_count": len(emails),
        "matches": matches,
        "warnings": [],
    }
