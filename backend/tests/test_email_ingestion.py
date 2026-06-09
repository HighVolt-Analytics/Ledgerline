"""Tests for Microsoft Graph email ingestion."""

import base64
from unittest.mock import patch

from app.services.attachment_filter import filter_invoice_attachments
from app.services.email_ingestion import (
    EmailAttachment,
    RawEmail,
    poll_inbox,
)


def test_poll_skipped_when_not_configured() -> None:
    with patch("app.services.email_ingestion.is_graph_enabled", return_value=False):
        assert poll_inbox("user@example.com") == []


def test_list_unread_does_not_use_orderby() -> None:
    """Graph returns 400 if $orderby is combined with $filter on messages."""
    with (
        patch("app.services.email_ingestion.is_graph_enabled", return_value=True),
        patch("app.services.email_ingestion.graph_request") as mock_graph,
    ):
        mock_graph.return_value = {"value": []}
        from app.services.email_ingestion import _list_unread_messages

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
        patch("app.services.email_ingestion.is_graph_enabled", return_value=True),
        patch(
            "app.services.email_ingestion._list_unread_messages",
            return_value=messages,
        ),
        patch(
            "app.services.email_ingestion._list_attachments",
            return_value=attachments,
        ),
    ):
        emails = poll_inbox("vendor@example.com")

    assert len(emails) == 1
    assert emails[0].message_id == "msg-1"
    assert emails[0].sender == "vendor@example.com"
    assert len(emails[0].attachments) == 1
    assert emails[0].attachments[0].filename == "invoice-march.pdf"


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
