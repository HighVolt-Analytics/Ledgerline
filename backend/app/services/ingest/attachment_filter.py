"""Keep email attachments that match accepted invoice/receipt formats."""

from __future__ import annotations

from app.services.ingest.email_ingestion import EmailAttachment, RawEmail
from app.services.ingest.ingest_file_types import (
    ensure_filename_extension,
    is_allowed_document,
)


def _is_invoice_attachment(att: EmailAttachment) -> bool:
    return is_allowed_document(filename=att.filename, content_type=att.content_type)


def filter_invoice_attachments(email: RawEmail) -> list[EmailAttachment]:
    """PDF, JPG/PNG/WEBP, and DOCX attachments (brief + WhatsApp parity).

    Filtered-out attachments are recorded on ``email.attachment_drops`` for durable audit.
    Missing extensions are filled from MIME when the type is otherwise allowed.
    """
    kept: list[EmailAttachment] = []
    for att in email.attachments:
        if not _is_invoice_attachment(att):
            email.attachment_drops.append(
                {
                    "reason": "attachment_type_filtered",
                    "filename": att.filename or "",
                }
            )
            continue
        fixed_name = ensure_filename_extension(att.filename, att.content_type)
        if fixed_name != (att.filename or ""):
            kept.append(
                EmailAttachment(
                    filename=fixed_name,
                    content_type=att.content_type,
                    data=att.data,
                )
            )
        else:
            kept.append(att)
    return kept
