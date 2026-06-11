"""Tests for Phase 6 Graph folder routing."""

import pytest

from app.models.invoice import InvoiceStatus
from app.services.graph_mail_folders import (
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


def test_classify_exception_or_duplicate() -> None:
    assert classify_message_outcome([InvoiceStatus.EXCEPTION]) == "exception"
    assert classify_message_outcome([InvoiceStatus.DUPLICATE_SKIPPED]) == "exception"
    assert (
        classify_message_outcome(
            [InvoiceStatus.PROCESSED, InvoiceStatus.EXCEPTION]
        )
        == "exception"
    )


@pytest.mark.asyncio
async def test_finalize_preskip_moves_exception(
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
    ) -> bool:
        moves.append((message_id, outcome))
        return True

    monkeypatch.setattr(
        "app.services.graph_mail_folders.folder_moves_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.graph_mail_folders.move_message_to_folder",
        fake_move,
    )

    moved = await finalize_graph_messages(
        db_session,
        ["msg-skip-1"],
        preskip_exceptions={"msg-skip-1": "no_attachments"},
    )
    assert moved == 1
    assert moves == [("msg-skip-1", "exception")]


def test_move_falls_back_to_mark_read_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    marked: list[str] = []

    monkeypatch.setattr(
        "app.services.graph_mail_folders.folder_moves_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.services.graph_mail_folders.mark_message_read",
        lambda mid, mailbox_email, access_token=None: marked.append(mid) or True,
    )

    assert move_message_to_folder(
        "msg-1", "processed", mailbox_email="user@test.com"
    ) is True
    assert marked == ["msg-1"]
    clear_folder_cache()
