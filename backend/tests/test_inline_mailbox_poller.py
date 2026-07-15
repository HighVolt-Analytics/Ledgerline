"""Inline mailbox poller (sync-processing local dev)."""

from unittest.mock import patch

from app.services.ingest.inline_mailbox_poller import start_inline_mailbox_poller


def test_start_skipped_when_sync_processing_disabled() -> None:
    with patch("app.services.ingest.inline_mailbox_poller.get_settings") as mock_settings:
        mock_settings.return_value.sync_processing = False
        assert start_inline_mailbox_poller() is None


def test_start_skipped_when_no_mailbox_provider_configured() -> None:
    with (
        patch("app.services.ingest.inline_mailbox_poller.get_settings") as mock_settings,
        patch("app.services.ingest.inline_mailbox_poller.is_graph_enabled", return_value=False),
        patch(
            "app.services.ingest.inline_mailbox_poller.gmail_oauth_configured",
            return_value=False,
        ),
    ):
        mock_settings.return_value.sync_processing = True
        assert start_inline_mailbox_poller() is None


def test_start_allowed_when_only_gmail_configured() -> None:
    with (
        patch("app.services.ingest.inline_mailbox_poller.get_settings") as mock_settings,
        patch("app.services.ingest.inline_mailbox_poller.is_graph_enabled", return_value=False),
        patch(
            "app.services.ingest.inline_mailbox_poller.gmail_oauth_configured",
            return_value=True,
        ),
        patch("app.services.ingest.inline_mailbox_poller.asyncio.create_task") as mock_create,
    ):
        mock_settings.return_value.sync_processing = True
        mock_settings.return_value.graph_poll_interval_minutes = 2
        mock_create.return_value = object()
        assert start_inline_mailbox_poller() is not None
        mock_create.assert_called_once()
