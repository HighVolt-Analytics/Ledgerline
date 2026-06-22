"""Send login OTP emails via SMTP."""

import smtplib
from email.message import EmailMessage

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def send_login_otp_email(*, to_email: str, otp: str) -> None:
    settings = get_settings()
    if not settings.is_production:
        logger.info("dev_otp_email", extra={"email": to_email, "otp": otp})
        return

    msg = EmailMessage()
    msg["Subject"] = "Your LedgerLink login code"
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg.set_content(f"Your verification code is: {otp}\n\nThis code expires in 5 minutes.")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.send_message(msg)
