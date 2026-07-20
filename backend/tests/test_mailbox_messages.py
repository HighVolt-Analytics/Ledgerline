"""Phase 3: mailbox_messages lifecycle + Message-ID forward edge case."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connected_mailbox import (
    MAIL_PROVIDER_GOOGLE,
    MAIL_PROVIDER_MICROSOFT,
    STATUS_CONNECTED,
    ConnectedMailbox,
)
from app.models.mailbox_message import (
    OUTCOME_PENDING,
    OUTCOME_PROCESSED,
    OUTCOME_SKIPPED,
    MailboxMessage,
)
from app.services.ingest.graph_mail_folders import finalize_graph_messages
from app.services.ingest.mailbox_message_service import (
    upsert_pending_mailbox_message,
)
from app.tenant_ids import TESTING_TENANT_UUID


async def _mailbox(
    session: AsyncSession,
    *,
    email: str = "ap@example.com",
    provider: str = MAIL_PROVIDER_MICROSOFT,
) -> ConnectedMailbox:
    mb = ConnectedMailbox(
        tenant_id=TESTING_TENANT_UUID,
        email=email,
        is_active=True,
        mail_provider=provider,
        connection_status=STATUS_CONNECTED,
        auth_type="application",
    )
    session.add(mb)
    await session.flush()
    return mb


@pytest.mark.asyncio
async def test_same_stable_message_id_does_not_open_second_lifecycle(
    db_session: AsyncSession,
) -> None:
    """Forward/reply clients that reuse Message-ID must not create a second open row."""
    mb = await _mailbox(db_session)
    first = await upsert_pending_mailbox_message(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        connected_mailbox_id=mb.id,
        provider=MAIL_PROVIDER_MICROSOFT,
        stable_message_id="<shared-id@example.com>",
        provider_message_id="graph-aaa",
    )
    second = await upsert_pending_mailbox_message(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        connected_mailbox_id=mb.id,
        provider=MAIL_PROVIDER_MICROSOFT,
        stable_message_id="<shared-id@example.com>",
        provider_message_id="graph-bbb",
    )
    assert first.id == second.id
    assert second.provider_message_id == "graph-bbb"
    assert second.outcome == OUTCOME_PENDING

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(MailboxMessage)
            .where(
                MailboxMessage.connected_mailbox_id == mb.id,
                MailboxMessage.stable_message_id == "<shared-id@example.com>",
            )
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_forward_with_different_message_id_is_new_row(
    db_session: AsyncSession,
) -> None:
    mb = await _mailbox(db_session)
    original = await upsert_pending_mailbox_message(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        connected_mailbox_id=mb.id,
        provider=MAIL_PROVIDER_MICROSOFT,
        stable_message_id="<original@example.com>",
        provider_message_id="graph-1",
    )
    forwarded = await upsert_pending_mailbox_message(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        connected_mailbox_id=mb.id,
        provider=MAIL_PROVIDER_MICROSOFT,
        stable_message_id="<forwarded@example.com>",
        provider_message_id="graph-2",
    )
    assert original.id != forwarded.id
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(MailboxMessage)
            .where(MailboxMessage.connected_mailbox_id == mb.id)
        )
    ).scalar_one()
    assert count == 2


@pytest.mark.asyncio
async def test_gmail_finalize_sets_db_outcome_without_folder_move(
    db_session: AsyncSession,
) -> None:
    mb = await _mailbox(
        db_session,
        email="gmail-user@gmail.com",
        provider=MAIL_PROVIDER_GOOGLE,
    )
    await upsert_pending_mailbox_message(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        connected_mailbox_id=mb.id,
        provider=MAIL_PROVIDER_GOOGLE,
        stable_message_id="<gmail-1@example.com>",
        provider_message_id="gmail-provider-1",
    )

    moved = await finalize_graph_messages(
        db_session,
        ["<gmail-1@example.com>"],
        tenant_id=TESTING_TENANT_UUID,
        preskip_exceptions={"<gmail-1@example.com>": "no_attachments"},
        message_mailbox_emails={"<gmail-1@example.com>": mb.email},
        message_graph_ids={"<gmail-1@example.com>": "gmail-provider-1"},
    )
    assert moved == 0

    row = (
        await db_session.execute(
            select(MailboxMessage).where(
                MailboxMessage.connected_mailbox_id == mb.id,
                MailboxMessage.stable_message_id == "<gmail-1@example.com>",
            )
        )
    ).scalars().one()
    assert row.outcome == OUTCOME_SKIPPED
    assert row.skip_reason == "no_attachments"
    assert row.folder_synced_at is not None


@pytest.mark.asyncio
async def test_capture_rule_miss_is_retryable_not_known(
    db_session: AsyncSession,
) -> None:
    """After no_capture_rule_match, the message must be re-fetched so rule fixes work."""
    from app.services.ingest.mailbox_message_service import (
        known_terminal_mailbox_message_ids,
        set_mailbox_message_outcome,
    )

    mb = await _mailbox(db_session)
    await upsert_pending_mailbox_message(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        connected_mailbox_id=mb.id,
        provider=MAIL_PROVIDER_MICROSOFT,
        stable_message_id="<hv-subject@example.com>",
        provider_message_id="graph-hv-1",
    )
    await set_mailbox_message_outcome(
        db_session,
        connected_mailbox_id=mb.id,
        stable_message_id="<hv-subject@example.com>",
        outcome=OUTCOME_SKIPPED,
        skip_reason="no_capture_rule_match",
    )
    await db_session.flush()

    known = await known_terminal_mailbox_message_ids(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert "<hv-subject@example.com>" not in known

    reopened = await upsert_pending_mailbox_message(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        connected_mailbox_id=mb.id,
        provider=MAIL_PROVIDER_MICROSOFT,
        stable_message_id="<hv-subject@example.com>",
        provider_message_id="graph-hv-1",
    )
    assert reopened.outcome == OUTCOME_PENDING
    assert reopened.skip_reason is None


@pytest.mark.asyncio
async def test_no_attachments_skip_stays_known(
    db_session: AsyncSession,
) -> None:
    from app.services.ingest.mailbox_message_service import (
        known_terminal_mailbox_message_ids,
        set_mailbox_message_outcome,
    )

    mb = await _mailbox(db_session, email="ap2@example.com")
    await upsert_pending_mailbox_message(
        db_session,
        tenant_id=TESTING_TENANT_UUID,
        connected_mailbox_id=mb.id,
        provider=MAIL_PROVIDER_MICROSOFT,
        stable_message_id="<no-att@example.com>",
    )
    await set_mailbox_message_outcome(
        db_session,
        connected_mailbox_id=mb.id,
        stable_message_id="<no-att@example.com>",
        outcome=OUTCOME_SKIPPED,
        skip_reason="no_attachments",
    )
    await db_session.flush()

    known = await known_terminal_mailbox_message_ids(
        db_session, tenant_id=TESTING_TENANT_UUID
    )
    assert "<no-att@example.com>" in known
