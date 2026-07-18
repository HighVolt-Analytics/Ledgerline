import smtplib
from email.mime.text import MIMEText

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.utils.logger import get_logger

logger = get_logger(__name__)


def send_notification(invoice: Invoice, status: InvoiceStatus) -> bool:
    """Best-effort status email. Skips when SMTP is not a real relay (local defaults)."""
    settings = get_settings()
    if not settings.smtp_explicitly_configured:
        logger.debug(
            "notify_skipped",
            invoice_id=invoice.id,
            reason="smtp_not_configured",
            smtp_host=settings.smtp_host,
        )
        return False

    body = (
        f"Invoice {invoice.invoice_no or invoice.id}\n"
        f"Vendor: {invoice.vendor}\n"
        f"Status: {status.value}\n"
        f"Total: {invoice.total} {invoice.currency}\n"
    )
    msg = MIMEText(body)
    msg["Subject"] = f"Invoice update: {status.value}"
    msg["From"] = settings.smtp_from
    msg["To"] = settings.smtp_from

    try:
        # Short timeout — never stall the pipeline / event loop for mail.
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=2) as smtp:
            smtp.send_message(msg)
        return True
    except OSError as exc:
        logger.warning("notify_failed", invoice_id=invoice.id, error=str(exc))
        return False
