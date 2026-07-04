"""Inline mailbox poller (sync-processing local dev)."""

from unittest.mock import patch

from app.services.ingest.inline_mailbox_poller import start_inline_mailbox_poller


def test_start_skipped_when_sync_processing_disabled() -> None:
    with patch("app.services.ingest.inline_mailbox_poller.get_settings") as mock_settings:
        mock_settings.return_value.sync_processing = False
        assert start_inline_mailbox_poller() is None


def test_start_skipped_when_graph_disabled() -> None:
    with (
        patch("app.services.ingest.inline_mailbox_poller.get_settings") as mock_settings,
        patch("app.services.ingest.inline_mailbox_poller.is_graph_enabled", return_value=False),
    ):
        mock_settings.return_value.sync_processing = True
        assert start_inline_mailbox_poller() is None
