"""Tests for Phase 6 Graph folder routing."""

import pytest

from app.models.invoice import InvoiceStatus
from app.services.ingest.graph_mail_folders import (
    classify_message_outcome,
    clear_folder_cache,
    finalize_graph_messages,
    move_message_to_folder,
)


def test_classify_all_processed() -> None:
    assert classify_message_outcome([InvoiceStatus.PROCESSED]) == "processed"
    assert (
        classify_message_outcome([InvoiceStatus.PROCESSED, InvoiceStatus.PROCESSED])
        == "processed"
    )
    assert classify_message_outcome([InvoiceStatus.DUPLICATE_SKIPPED]) == "processed"
    assert (
        classify_message_outcome(
            [InvoiceStatus.PROCESSED, InvoiceStatus.DUPLICATE_SKIPPED]
        )
        == "processed"
    )


def test_classify_exception_or_mixed() -> None:
    assert classify_message_outcome([InvoiceStatus.EXCEPTION]) == "exception"
    assert (
        classify_message_outcome(
            [InvoiceStatus.PROCESSED, InvoiceStatus.EXCEPTION]
        )
        == "exception"
    )


@pytest.mark.asyncio
async def test_finalize_preskip_moves_processed_for_intentional_skip(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moves: list[tuple[str, str]] = []

    def fake_move(
        message_id: str,
        outcome: str,
        *,
        mailbox_email: str,
        access_token: str | None = None,
    ) -> str | None:
        moves.append((message_id, outcome))
        return message_id

    monkeypatch.setattr(
        "app.services.ingest.graph_mail_folders.folder_moves_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.ingest.graph_mail_folders.move_message_to_folder",
        fake_move,
    )

    moved = await finalize_graph_messages(
        db_session,
        ["msg-skip-1"],
        preskip_exceptions={"msg-skip-1": "no_attachments"},
        message_mailbox_emails={"msg-skip-1": "support@example.com"},
    )
    assert moved == 1
    assert moves == [("msg-skip-1", "processed")]


@pytest.mark.asyncio
async def test_finalize_no_capture_rule_match_moves_processed(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moves: list[tuple[str, str]] = []

    def fake_move(
        message_id: str,
        outcome: str,
        *,
        mailbox_email: str,
        access_token: str | None = None,
    ) -> str | None:
        moves.append((message_id, outcome))
        return message_id

    monkeypatch.setattr(
        "app.services.ingest.graph_mail_folders.folder_moves_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.ingest.graph_mail_folders.move_message_to_folder",
        fake_move,
    )

    moved = await finalize_graph_messages(
        db_session,
        ["msg-skip-2"],
        preskip_exceptions={"msg-skip-2": "no_capture_rule_match"},
        message_mailbox_emails={"msg-skip-2": "support@example.com"},
    )
    assert moved == 1
    assert moves == [("msg-skip-2", "processed")]


@pytest.mark.asyncio
async def test_finalize_already_imported_moves_processed(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moves: list[tuple[str, str]] = []

    def fake_move(
        message_id: str,
        outcome: str,
        *,
        mailbox_email: str,
        access_token: str | None = None,
    ) -> str | None:
        moves.append((message_id, outcome))
        return message_id

    monkeypatch.setattr(
        "app.services.ingest.graph_mail_folders.folder_moves_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.ingest.graph_mail_folders.move_message_to_folder",
        fake_move,
    )

    moved = await finalize_graph_messages(
        db_session,
        ["msg-known-1"],
        preskip_exceptions={"msg-known-1": "message_already_imported"},
        message_mailbox_emails={"msg-known-1": "support@example.com"},
        message_graph_ids={"msg-known-1": "graph-id-1"},
    )
    assert moved == 1
    assert moves == [("graph-id-1", "processed")]


@pytest.mark.asyncio
async def test_finalize_preskip_scopes_duplicate_mailbox_email(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same mailbox email on two tenants must not raise MultipleResultsFound."""
    import uuid

    from app.models.connected_mailbox import (
        AUTH_DELEGATED,
        STATUS_CONNECTED,
        ConnectedMailbox,
    )
    from app.models.tenant import Tenant

    tenant_a = Tenant(id=uuid.uuid4(), name="Org A", slug="org-a-mail-dup")
    tenant_b = Tenant(id=uuid.uuid4(), name="Org B", slug="org-b-mail-dup")
    db_session.add_all([tenant_a, tenant_b])
    await db_session.flush()

    for tenant in (tenant_a, tenant_b):
        db_session.add(
            ConnectedMailbox(
                tenant_id=tenant.id,
                email="shared@example.com",
                auth_type=AUTH_DELEGATED,
                connection_status=STATUS_CONNECTED,
                access_token_encrypted="x",
                refresh_token_encrypted="y",
                is_active=True,
            )
        )
    await db_session.flush()

    moves: list[tuple[str, str]] = []

    def fake_move(
        message_id: str,
        outcome: str,
        *,
        mailbox_email: str,
        access_token: str | None = None,
    ) -> str | None:
        moves.append((message_id, outcome))
        return message_id

    async def fake_token(*_a, **_k):
        raise RuntimeError("skip token")

    monkeypatch.setattr(
        "app.services.ingest.graph_mail_folders.folder_moves_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.ingest.graph_mail_folders.move_message_to_folder",
        fake_move,
    )
    monkeypatch.setattr(
        "app.services.ingest.mailbox_oauth_service.resolve_mailbox_access_token",
        fake_token,
    )

    moved = await finalize_graph_messages(
        db_session,
        ["msg-dup-1"],
        tenant_id=tenant_a.id,
        preskip_exceptions={"msg-dup-1": "no_invoice_attachments"},
        message_mailbox_emails={"msg-dup-1": "shared@example.com"},
    )
    assert moved == 1
    assert moves == [("msg-dup-1", "processed")]


def test_move_falls_back_to_mark_read_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    marked: list[str] = []

    monkeypatch.setattr(
        "app.services.ingest.graph_mail_folders.folder_moves_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.services.ingest.graph_mail_folders.mark_message_read",
        lambda mid, mailbox_email, access_token=None: marked.append(mid) or True,
    )

    assert move_message_to_folder(
        "msg-1", "processed", mailbox_email="user@test.com"
    ) == "msg-1"
    assert marked == ["msg-1"]
    clear_folder_cache()
