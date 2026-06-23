"""Send auth and tenant-invite emails via Graph or SMTP."""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from app.config import get_settings
from app.services.graph_mail_sender import graph_mail_send_configured, send_graph_mail
from app.tenant_roles import format_tenant_role_label
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class InviteEmailResult:
    sent: bool
    error: str | None = None


def _send_via_smtp(*, to_email: str, subject: str, body_text: str) -> InviteEmailResult:
    settings = get_settings()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg.set_content(body_text)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.send_message(msg)
        return InviteEmailResult(sent=True)
    except OSError as exc:
        logger.warning(
            "smtp_send_failed",
            to=to_email,
            host=settings.smtp_host,
            port=settings.smtp_port,
            error=str(exc),
        )
        return InviteEmailResult(
            sent=False,
            error=f"SMTP failed ({settings.smtp_host}:{settings.smtp_port}).",
        )


async def send_login_otp_email(*, to_email: str, otp: str) -> None:
    settings = get_settings()
    if not settings.is_production:
        logger.info("dev_otp_email", extra={"email": to_email, "otp": otp})
        return

    _send_via_smtp(
        to_email=to_email,
        subject="Your LedgerLink login code",
        body_text=f"Your verification code is: {otp}\n\nThis code expires in 5 minutes.",
    )


async def send_tenant_invite_email(
    *,
    to_email: str,
    tenant_name: str,
    role: str,
    accept_url: str,
) -> InviteEmailResult:
    """Deliver tenant member invite — Graph Mail.Send when configured, else SMTP."""
    settings = get_settings()
    role_label = format_tenant_role_label(role)
    subject = f"You've been invited to {tenant_name} on LedgerLink"
    body_text = (
        f"You have been invited to join {tenant_name} as {role_label}.\n\n"
        f"Accept your invitation and set your password:\n{accept_url}\n\n"
        "This link expires in 7 days.\n\n"
        "If you did not expect this invitation, you can ignore this email."
    )
    body_html = (
        f"<p>You have been invited to join <strong>{tenant_name}</strong> "
        f"as <strong>{role_label}</strong>.</p>"
        f'<p><a href="{accept_url}">Accept invitation and set your password</a></p>'
        "<p>This link expires in 7 days.</p>"
        "<p>If you did not expect this invitation, you can ignore this email.</p>"
    )

    if not settings.is_production:
        logger.info(
            "tenant_invite_email",
            extra={
                "email": to_email,
                "tenant": tenant_name,
                "role": role,
                "accept_url": accept_url,
            },
        )

    if graph_mail_send_configured():
        graph_result = send_graph_mail(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
        if graph_result.sent:
            return InviteEmailResult(sent=True)
        logger.warning(
            "tenant_invite_graph_failed",
            extra={"email": to_email, "error": graph_result.error},
        )
        smtp_result = _send_via_smtp(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
        )
        if smtp_result.sent:
            return InviteEmailResult(sent=True)
        return InviteEmailResult(
            sent=False,
            error=graph_result.error or smtp_result.error,
        )

    smtp_result = _send_via_smtp(
        to_email=to_email,
        subject=subject,
        body_text=body_text,
    )
    if smtp_result.sent:
        return InviteEmailResult(sent=True)

    if not settings.is_production:
        return InviteEmailResult(
            sent=False,
            error=(
                smtp_result.error
                or "Email not sent in development. Copy the invite link from the invite dialog "
                "or configure GRAPH_MAILBOX + Azure credentials, or run a local SMTP catcher on port 1025."
            ),
        )

    return smtp_result
