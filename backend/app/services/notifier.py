import smtplib
from email.mime.text import MIMEText

from app.config import get_settings
from app.models.invoice import Invoice, InvoiceStatus
from app.utils.logger import get_logger

logger = get_logger(__name__)


def send_notification(invoice: Invoice, status: InvoiceStatus) -> bool:
    settings = get_settings()
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
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.send_message(msg)
        return True
    except OSError as exc:
        logger.warning("notify_failed", invoice_id=invoice.id, error=str(exc))
        return False
