"""Upsert and finalize mailbox_messages lifecycle rows."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connected_mailbox import ConnectedMailbox
from app.models.mailbox_message import (
    OUTCOME_EXCEPTION,
    OUTCOME_PENDING,
    OUTCOME_PROCESSED,
    OUTCOME_SKIPPED,
    TERMINAL_OUTCOMES,
    MailboxMessage,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Preskip reasons that mean intentional skip (Processed folder), not Exceptions.
_SKIPPED_PRESKIP_REASONS = frozenset(
    {
        "message_already_imported",
        "no_attachments",
        "no_invoice_attachments",
        "attachment_type_filtered",
        "no_capture_rule_match",
    }
)


async def upsert_pending_mailbox_message(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    connected_mailbox_id: int,
    provider: str,
    stable_message_id: str,
    provider_message_id: str | None = None,
) -> MailboxMessage:
    """
    Ensure one lifecycle row per (mailbox, stable_message_id).

    Second insert with the same stable id updates provider id / leaves terminal
    outcomes alone (does not invent a second open lifecycle).
    """
    stmt = select(MailboxMessage).where(
        MailboxMessage.connected_mailbox_id == connected_mailbox_id,
        MailboxMessage.stable_message_id == stable_message_id,
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is not None:
        if provider_message_id and row.provider_message_id != provider_message_id:
            row.provider_message_id = provider_message_id
        if row.outcome not in TERMINAL_OUTCOMES:
            row.outcome = OUTCOME_PENDING
            row.skip_reason = None
        return row

    row = MailboxMessage(
        tenant_id=tenant_id,
        connected_mailbox_id=connected_mailbox_id,
        provider=provider,
        stable_message_id=stable_message_id,
        provider_message_id=provider_message_id,
        outcome=OUTCOME_PENDING,
    )
    session.add(row)
    await session.flush()
    return row


async def set_mailbox_message_outcome(
    session: AsyncSession,
    *,
    connected_mailbox_id: int,
    stable_message_id: str,
    outcome: str,
    skip_reason: str | None = None,
    provider_message_id: str | None = None,
    folder_synced: bool = False,
) -> MailboxMessage | None:
    stmt = select(MailboxMessage).where(
        MailboxMessage.connected_mailbox_id == connected_mailbox_id,
        MailboxMessage.stable_message_id == stable_message_id,
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        return None
    row.outcome = outcome
    row.skip_reason = skip_reason
    if provider_message_id:
        row.provider_message_id = provider_message_id
    if folder_synced:
        row.folder_synced_at = datetime.now(timezone.utc)
    return row


async def known_terminal_mailbox_message_ids(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> frozenset[str]:
    rows = (
        await session.execute(
            select(MailboxMessage.stable_message_id).where(
                MailboxMessage.tenant_id == tenant_id,
                MailboxMessage.outcome.in_(tuple(TERMINAL_OUTCOMES)),
            )
        )
    ).scalars().all()
    return frozenset(str(row) for row in rows if row)


def outcome_for_preskip_reason(reason: str) -> str:
    if reason in _SKIPPED_PRESKIP_REASONS:
        return OUTCOME_SKIPPED
    if reason in {"integrity_error", "ingest_error", "ingest_integrity_error", "ingest_message_failed"}:
        return OUTCOME_EXCEPTION
    return OUTCOME_EXCEPTION


async def apply_preskip_mailbox_outcomes(
    session: AsyncSession,
    *,
    connected_mailbox_id: int,
    tenant_id: uuid.UUID,
    provider: str,
    preskip_exceptions: dict[str, str],
    message_graph_ids: dict[str, str] | None = None,
) -> None:
    graph_ids = message_graph_ids or {}
    for stable_id, reason in preskip_exceptions.items():
        await upsert_pending_mailbox_message(
            session,
            tenant_id=tenant_id,
            connected_mailbox_id=connected_mailbox_id,
            provider=provider,
            stable_message_id=stable_id,
            provider_message_id=graph_ids.get(stable_id),
        )
        await set_mailbox_message_outcome(
            session,
            connected_mailbox_id=connected_mailbox_id,
            stable_message_id=stable_id,
            outcome=outcome_for_preskip_reason(reason),
            skip_reason=reason,
            provider_message_id=graph_ids.get(stable_id),
        )


async def ensure_pending_for_emails(
    session: AsyncSession,
    *,
    mailbox: ConnectedMailbox,
    emails: list,
) -> None:
    for email in emails:
        stable = getattr(email, "message_id", None)
        if not stable:
            continue
        await upsert_pending_mailbox_message(
            session,
            tenant_id=mailbox.tenant_id,
            connected_mailbox_id=mailbox.id,
            provider=mailbox.mail_provider,
            stable_message_id=str(stable),
            provider_message_id=getattr(email, "graph_id", None) or None,
        )
