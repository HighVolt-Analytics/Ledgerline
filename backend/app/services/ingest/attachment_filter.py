import re
from pathlib import Path

from app.services.ingest.email_ingestion import EmailAttachment, RawEmail

_INVOICE_NAME = re.compile(r"(invoice|inv|bill|tax.?invoice)", re.I)
_PDF_MIME = {"application/pdf", "application/x-pdf"}
_IMAGE_MIME = {"image/jpeg", "image/jpg", "image/png"}
_DOCX_MIME = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_ALLOWED_SUFFIX = {".pdf", ".jpg", ".jpeg", ".png", ".docx"}


def _is_invoice_attachment(att: EmailAttachment) -> bool:
    mime = (att.content_type or "application/octet-stream").split(";")[0].strip().lower()
    name = (att.filename or "").lower()
    if not name:
        return False
    suffix = Path(name).suffix.lower()

    is_pdf = mime in _PDF_MIME or suffix == ".pdf"
    is_image = mime in _IMAGE_MIME or suffix in {".jpg", ".jpeg", ".png"}
    is_docx = mime in _DOCX_MIME or suffix == ".docx"

    if suffix not in _ALLOWED_SUFFIX and not (is_pdf or is_image or is_docx):
        return False

    if _INVOICE_NAME.search(name):
        return True
    return suffix in _ALLOWED_SUFFIX


def filter_invoice_attachments(email: RawEmail) -> list[EmailAttachment]:
    """PDF, JPG/PNG, and DOCX attachments per assessment brief §2.

    Filtered-out attachments are recorded on ``email.attachment_drops`` for durable audit.
    """
    kept: list[EmailAttachment] = []
    for att in email.attachments:
        if _is_invoice_attachment(att):
            kept.append(att)
        else:
            email.attachment_drops.append(
                {
                    "reason": "attachment_type_filtered",
                    "filename": att.filename or "",
                }
            )
    return kept
