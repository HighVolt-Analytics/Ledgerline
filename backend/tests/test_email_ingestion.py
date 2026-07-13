"""Tests for Microsoft Graph email ingestion."""

import base64
from datetime import datetime, timezone
from unittest.mock import patch

from app.services.ingest.attachment_filter import filter_invoice_attachments
from app.services.ingest.email_ingestion import (
    EmailAttachment,
    RawEmail,
    build_recent_inbox_filter,
    poll_inbox,
)


def test_poll_skipped_when_not_configured() -> None:
    with patch("app.services.ingest.email_ingestion.is_graph_enabled", return_value=False):
        assert poll_inbox("user@example.com") == []


def test_build_recent_inbox_filter() -> None:
    filt = build_recent_inbox_filter(datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc))
    assert "receivedDateTime ge 2026-03-01T12:00:00Z" in filt
    assert "hasAttachments eq true" in filt
    assert "isRead" not in filt


def test_list_unread_does_not_use_orderby() -> None:
    """Graph returns 400 if $orderby is combined with $filter on messages."""
    with (
        patch("app.services.ingest.email_ingestion.is_graph_enabled", return_value=True),
        patch("app.services.ingest.email_ingestion.graph_request") as mock_graph,
    ):
        mock_graph.return_value = {"value": []}
        from app.services.ingest.email_ingestion import _list_unread_messages

        _list_unread_messages("user@example.com")
        _params = mock_graph.call_args.kwargs.get("params") or mock_graph.call_args[1].get("params")
        assert "$orderby" not in (_params or {})


def test_poll_parses_messages() -> None:
    messages = [
        {
            "id": "msg-1",
            "subject": "Invoice March",
            "from": {"emailAddress": {"address": "vendor@example.com"}},
            "hasAttachments": True,
        }
    ]
    attachments = [
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "invoice-march.pdf",
            "contentType": "application/pdf",
            "contentBytes": base64.b64encode(b"%PDF-1.4").decode(),
        }
    ]

    with (
        patch("app.services.ingest.email_ingestion.is_graph_enabled", return_value=True),
        patch(
            "app.services.ingest.email_ingestion._exceptions_folder_id",
            return_value=None,
        ),
        patch(
            "app.services.ingest.email_ingestion._list_unread_messages",
            return_value=messages,
        ),
        patch(
            "app.services.ingest.email_ingestion._list_attachments",
            return_value=attachments,
        ),
    ):
        emails = poll_inbox("vendor@example.com")

    assert len(emails) == 1
    assert emails[0].message_id == "msg-1"
    assert emails[0].sender == "vendor@example.com"
    assert len(emails[0].attachments) == 1
    assert emails[0].attachments[0].filename == "invoice-march.pdf"


def test_poll_skips_known_message_ids() -> None:
    messages = [
        {
            "id": "msg-known",
            "subject": "Invoice March",
            "from": {"emailAddress": {"address": "vendor@example.com"}},
            "hasAttachments": True,
        }
    ]

    with (
        patch("app.services.ingest.email_ingestion.is_graph_enabled", return_value=True),
        patch(
            "app.services.ingest.email_ingestion._exceptions_folder_id",
            return_value=None,
        ),
        patch(
            "app.services.ingest.email_ingestion._list_unread_messages",
            return_value=messages,
        ),
        patch("app.services.ingest.email_ingestion._list_attachments") as mock_attachments,
    ):
        mock_attachments.return_value = []
        emails = poll_inbox(
            "vendor@example.com",
            known_message_ids=frozenset({"msg-known"}),
        )

    assert emails == []
    mock_attachments.assert_not_called()


def test_poll_merges_unread_and_recent_without_duplicates() -> None:
    unread = [
        {
            "id": "msg-1",
            "subject": "Unread",
            "from": {"emailAddress": {"address": "vendor@example.com"}},
            "hasAttachments": True,
        }
    ]
    recent = [
        {
            "id": "msg-1",
            "subject": "Unread",
            "from": {"emailAddress": {"address": "vendor@example.com"}},
            "hasAttachments": True,
        },
        {
            "id": "msg-2",
            "subject": "Recent read",
            "from": {"emailAddress": {"address": "vendor@example.com"}},
            "hasAttachments": True,
        },
    ]
    attachments = [
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "invoice.pdf",
            "contentType": "application/pdf",
            "contentBytes": base64.b64encode(b"%PDF-1.4").decode(),
        }
    ]

    with (
        patch("app.services.ingest.email_ingestion.is_graph_enabled", return_value=True),
        patch(
            "app.services.ingest.email_ingestion._exceptions_folder_id",
            return_value=None,
        ),
        patch(
            "app.services.ingest.email_ingestion._list_unread_messages",
            return_value=unread,
        ),
        patch(
            "app.services.ingest.email_ingestion._list_recent_messages",
            return_value=recent,
        ),
        patch(
            "app.services.ingest.email_ingestion._list_attachments",
            return_value=attachments,
        ),
    ):
        emails = poll_inbox(
            "vendor@example.com",
            since=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )

    assert {email.message_id for email in emails} == {"msg-1", "msg-2"}


def test_poll_includes_exceptions_folder_when_enabled() -> None:
    inbox_messages = [
        {
            "id": "msg-inbox",
            "subject": "Inbox",
            "from": {"emailAddress": {"address": "vendor@example.com"}},
            "hasAttachments": True,
        }
    ]
    exception_messages = [
        {
            "id": "msg-exc",
            "subject": "Exception retry",
            "from": {"emailAddress": {"address": "vendor@example.com"}},
            "hasAttachments": True,
        }
    ]
    attachments = [
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "invoice.pdf",
            "contentType": "application/pdf",
            "contentBytes": base64.b64encode(b"%PDF-1.4").decode(),
        }
    ]

    def list_unread(mailbox: str, *, access_token=None, folder_id=None):
        if folder_id == "exceptions-folder-id":
            return exception_messages
        return inbox_messages

    with (
        patch("app.services.ingest.email_ingestion.is_graph_enabled", return_value=True),
        patch(
            "app.services.ingest.email_ingestion._exceptions_folder_id",
            return_value="exceptions-folder-id",
        ),
        patch(
            "app.services.ingest.email_ingestion._list_unread_messages",
            side_effect=list_unread,
        ),
        patch(
            "app.services.ingest.email_ingestion._list_recent_messages",
            return_value=[],
        ),
        patch(
            "app.services.ingest.email_ingestion._list_attachments",
            return_value=attachments,
        ),
    ):
        emails = poll_inbox("vendor@example.com")

    assert {email.message_id for email in emails} == {"msg-inbox", "msg-exc"}


def test_filter_invoice_pdf() -> None:
    email = RawEmail(
        message_id="x",
        subject="Bill",
        sender="a@b.com",
        mailbox_email="a@b.com",
        attachments=[
            EmailAttachment("invoice.pdf", "application/pdf", b"data"),
            EmailAttachment("notes.txt", "text/plain", b"hi"),
        ],
    )
    files = filter_invoice_attachments(email)
    assert len(files) == 1
    assert files[0].filename == "invoice.pdf"


def test_filter_invoice_image_and_docx() -> None:
    email = RawEmail(
        message_id="x",
        subject="Bill",
        sender="a@b.com",
        mailbox_email="a@b.com",
        attachments=[
            EmailAttachment("scan.png", "image/png", b"data"),
            EmailAttachment("bill.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"data"),
            EmailAttachment("readme.txt", "text/plain", b"hi"),
        ],
    )
    files = filter_invoice_attachments(email)
    assert {f.filename for f in files} == {"scan.png", "bill.docx"}
