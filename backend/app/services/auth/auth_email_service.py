"""Send auth and tenant-invite emails via Graph or SMTP."""

from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from app.config import get_settings
from app.services.ingest.email_recipient_validation import (
    mask_email_for_log,
    validate_deliverable_email_or_raise,
)
from app.services.ingest.graph_mail_sender import graph_mail_send_configured, send_graph_mail
from app.tenant_roles import format_tenant_role_label
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Production OTP email requires (in app-secrets / env):
#   AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, GRAPH_MAILBOX
# Graph app registration needs Mail.Send (application) + admin consent.
# SMTP is only used in dev/preview, or production when SMTP_HOST is explicitly set.


@dataclass(frozen=True)
class InviteEmailResult:
    sent: bool
    error: str | None = None


def _send_via_smtp(*, to_email: str, subject: str, body_text: str) -> InviteEmailResult:
    settings = get_settings()
    masked = mask_email_for_log(to_email)
    if not settings.smtp_allowed_for_outbound:
        logger.warning(
            "smtp_send_skipped",
            extra={
                "email_masked": masked,
                "reason": "implicit_localhost_smtp_not_allowed_in_production",
                "smtp_host": settings.smtp_host,
                "smtp_port": settings.smtp_port,
            },
        )
        return InviteEmailResult(
            sent=False,
            error="SMTP is not configured for production (set SMTP_HOST or use Microsoft Graph).",
        )

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
            extra={
                "email_masked": masked,
                "smtp_host": settings.smtp_host,
                "smtp_port": settings.smtp_port,
                "error": str(exc),
            },
        )
        return InviteEmailResult(
            sent=False,
            error=f"SMTP failed ({settings.smtp_host}:{settings.smtp_port}).",
        )


def _otp_graph_failure_result(*, graph_error: str | None) -> InviteEmailResult:
    return InviteEmailResult(
        sent=False,
        error=graph_error or "Microsoft Graph could not send the verification email.",
    )


async def send_login_otp_email(*, to_email: str, otp: str) -> InviteEmailResult:
    """Send login OTP — Graph Mail.Send in production when configured, else SMTP."""
    settings = get_settings()
    masked = mask_email_for_log(to_email)

    if not settings.is_production:
        logger.info("dev_otp_email", extra={"email_masked": masked, "otp": otp})
        return InviteEmailResult(sent=True)

    validate_deliverable_email_or_raise(to_email)

    subject = "Your LedgerLink login code"
    body_text = (
        f"Your verification code is: {otp}\n\n"
        f"This code expires in {settings.otp_expire_minutes} minutes."
    )
    body_html = (
        f"<p>Your verification code is: <strong>{otp}</strong></p>"
        f"<p>This code expires in {settings.otp_expire_minutes} minutes.</p>"
    )

    if graph_mail_send_configured():
        logger.info(
            "login_otp_send_attempt",
            extra={"email_masked": masked, "channel": "graph"},
        )
        graph_result = send_graph_mail(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
        if graph_result.sent:
            logger.info(
                "login_otp_send_succeeded",
                extra={"email_masked": masked, "channel": "graph"},
            )
            return InviteEmailResult(sent=True)
        logger.warning(
            "login_otp_graph_failed",
            extra={
                "email_masked": masked,
                "channel": "graph",
                "error": graph_result.error,
            },
        )
        if not settings.smtp_allowed_for_outbound:
            logger.error(
                "login_otp_send_failed",
                extra={
                    "email_masked": masked,
                    "graph_error": graph_result.error,
                    "smtp_fallback": "skipped",
                },
            )
            return _otp_graph_failure_result(graph_error=graph_result.error)
        smtp_result = _send_via_smtp(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
        )
        if smtp_result.sent:
            logger.info(
                "login_otp_send_succeeded",
                extra={"email_masked": masked, "channel": "smtp_fallback"},
            )
            return InviteEmailResult(sent=True)
        logger.error(
            "login_otp_send_failed",
            extra={
                "email_masked": masked,
                "graph_error": graph_result.error,
                "smtp_error": smtp_result.error,
            },
        )
        return InviteEmailResult(
            sent=False,
            error=graph_result.error or smtp_result.error,
        )

    if settings.is_production:
        logger.error(
            "login_otp_send_failed",
            extra={
                "email_masked": masked,
                "graph_configured": False,
                "smtp_fallback": "skipped",
            },
        )
        return InviteEmailResult(
            sent=False,
            error="Microsoft Graph mail is not configured for production OTP delivery.",
        )

    logger.info(
        "login_otp_send_attempt",
        extra={"email_masked": masked, "channel": "smtp"},
    )
    smtp_result = _send_via_smtp(
        to_email=to_email,
        subject=subject,
        body_text=body_text,
    )
    if smtp_result.sent:
        logger.info(
            "login_otp_send_succeeded",
            extra={"email_masked": masked, "channel": "smtp"},
        )
        return InviteEmailResult(sent=True)

    logger.error(
        "login_otp_send_failed",
        extra={
            "email_masked": masked,
            "smtp_error": smtp_result.error,
            "graph_configured": False,
        },
    )
    return smtp_result


async def send_employee_mobile_access_email(
    *,
    to_email: str,
    tenant_name: str,
    sign_in_url: str,
) -> InviteEmailResult:
    """Email an existing Team member the mobile sign-in deep link (returnTo=/m)."""
    settings = get_settings()
    if settings.is_production or graph_mail_send_configured():
        validate_deliverable_email_or_raise(to_email)

    subject = f"Open {tenant_name} on LedgerLink mobile"
    body_text = (
        f"You already have a Team login for {tenant_name}.\n\n"
        f"Sign in to open the mobile capture app:\n{sign_in_url}\n\n"
        "If you did not expect this email, you can ignore it."
    )
    body_html = (
        f"<p>You already have a Team login for <strong>{tenant_name}</strong>.</p>"
        f'<p><a href="{sign_in_url}">Sign in to LedgerLink mobile</a></p>'
        "<p>After signing in you will land on the mobile capture app.</p>"
        "<p>If you did not expect this email, you can ignore it.</p>"
    )

    if not settings.is_production:
        logger.info(
            "employee_mobile_access_email",
            extra={
                "email": to_email,
                "tenant": tenant_name,
                "sign_in_url": sign_in_url,
            },
        )

    return await asyncio.to_thread(
        _deliver_tenant_invite_sync,
        to_email=to_email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
    )


async def send_tenant_invite_email(
    *,
    to_email: str,
    tenant_name: str,
    role: str,
    accept_url: str,
    for_mobile: bool = False,
) -> InviteEmailResult:
    """Deliver tenant member invite — Graph Mail.Send when configured, else SMTP."""
    settings = get_settings()
    if settings.is_production or graph_mail_send_configured():
        validate_deliverable_email_or_raise(to_email)
    role_label = format_tenant_role_label(role)
    if for_mobile:
        subject = f"Join {tenant_name} on LedgerLink mobile"
        body_text = (
            f"You have been invited to capture expenses for {tenant_name} on LedgerLink mobile.\n\n"
            f"Accept your invitation, set your password, then open the mobile app:\n{accept_url}\n\n"
            "This link expires in 7 days.\n\n"
            "If you did not expect this invitation, you can ignore this email."
        )
        body_html = (
            f"<p>You have been invited to capture expenses for "
            f"<strong>{tenant_name}</strong> on LedgerLink mobile.</p>"
            f'<p><a href="{accept_url}">Accept invitation and set your password</a></p>'
            "<p>After signing in you will land on the mobile capture app.</p>"
            "<p>This link expires in 7 days.</p>"
            "<p>If you did not expect this invitation, you can ignore this email.</p>"
        )
    else:
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

    # Sync Graph/SMTP must not block the asyncio loop (holds DB sessions + stalls all requests).
    return await asyncio.to_thread(
        _deliver_tenant_invite_sync,
        to_email=to_email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
    )


def _deliver_tenant_invite_sync(
    *,
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str,
) -> InviteEmailResult:
    settings = get_settings()
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
    return InviteEmailResult(
        sent=False,
        error=smtp_result.error or "Could not send invitation email",
    )


async def send_password_reset_otp_email(*, to_email: str, otp: str) -> InviteEmailResult:
    """Send password-reset OTP — same delivery rules as login OTP (Graph in prod)."""
    settings = get_settings()
    masked = mask_email_for_log(to_email)

    if not settings.is_production:
        logger.info("dev_password_reset_otp", extra={"email_masked": masked, "otp": otp})
        return InviteEmailResult(sent=True)

    validate_deliverable_email_or_raise(to_email)

    subject = "Your LedgerLink password reset code"
    body_text = (
        f"Your password reset code is: {otp}\n\n"
        f"This code expires in {settings.otp_expire_minutes} minutes.\n\n"
        "If you did not request a password reset, you can ignore this email."
    )
    body_html = (
        f"<p>Your password reset code is: <strong>{otp}</strong></p>"
        f"<p>This code expires in {settings.otp_expire_minutes} minutes.</p>"
        "<p>If you did not request a password reset, you can ignore this email.</p>"
    )

    if graph_mail_send_configured():
        logger.info(
            "password_reset_otp_send_attempt",
            extra={"email_masked": masked, "channel": "graph"},
        )
        graph_result = send_graph_mail(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
        if graph_result.sent:
            logger.info(
                "password_reset_otp_send_succeeded",
                extra={"email_masked": masked, "channel": "graph"},
            )
            return InviteEmailResult(sent=True)
        logger.warning(
            "password_reset_otp_graph_failed",
            extra={
                "email_masked": masked,
                "channel": "graph",
                "error": graph_result.error,
            },
        )
        if not settings.smtp_allowed_for_outbound:
            return _otp_graph_failure_result(graph_error=graph_result.error)
        smtp_result = _send_via_smtp(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
        )
        if smtp_result.sent:
            logger.info(
                "password_reset_otp_send_succeeded",
                extra={"email_masked": masked, "channel": "smtp_fallback"},
            )
            return InviteEmailResult(sent=True)
        return InviteEmailResult(
            sent=False,
            error=graph_result.error or smtp_result.error,
        )

    if settings.is_production:
        return InviteEmailResult(
            sent=False,
            error="Microsoft Graph mail is not configured for production password reset delivery.",
        )

    smtp_result = _send_via_smtp(
        to_email=to_email,
        subject=subject,
        body_text=body_text,
    )
    return smtp_result


def _format_confirmation_fields(fields: dict) -> str:
    lines: list[str] = []
    for key, value in fields.items():
        if key == "bank" and isinstance(value, dict):
            for bank_key, bank_val in value.items():
                if bank_val:
                    lines.append(f"{bank_key.replace('_', ' ').title()}: {bank_val}")
            continue
        if key == "billing_address" and isinstance(value, dict):
            parts = [str(v) for v in value.values() if v]
            if parts:
                lines.append(f"Address: {', '.join(parts)}")
            continue
        if isinstance(value, list):
            if value:
                lines.append(f"{key.replace('_', ' ').title()}: {', '.join(str(v) for v in value)}")
            continue
        if value:
            lines.append(f"{key.replace('_', ' ').title()}: {value}")
    return "\n".join(lines) if lines else "No details on file yet."


async def send_master_confirmation_email(
    *,
    to_email: str,
    party_name: str,
    kind: str,
    confirm_url: str,
    fields: dict,
) -> InviteEmailResult:
    """Send vendor/employee master confirmation link."""
    settings = get_settings()
    if settings.is_production or graph_mail_send_configured():
        validate_deliverable_email_or_raise(to_email)

    label = "employee" if kind == "employee" else "vendor"
    subject = f"Please confirm your {label} details — LedgerLink"
    detail_block = _format_confirmation_fields(fields)
    body_text = (
        f"Hello {party_name},\n\n"
        f"Please review and confirm your {label} details on file:\n\n"
        f"{detail_block}\n\n"
        f"Review, edit if needed, and confirm here:\n{confirm_url}\n\n"
        "This link expires in 7 days.\n\n"
        "If you did not expect this email, you can ignore it."
    )
    body_html = (
        f"<p>Hello <strong>{party_name}</strong>,</p>"
        f"<p>Please review and confirm your {label} details on file:</p>"
        f"<pre style=\"white-space:pre-wrap;font-family:inherit\">{detail_block}</pre>"
        f'<p><a href="{confirm_url}">Review and confirm your details</a></p>'
        "<p>This link expires in 7 days.</p>"
        "<p>If you did not expect this email, you can ignore it.</p>"
    )

    if not settings.is_production:
        logger.info(
            "master_confirmation_email",
            extra={
                "email": to_email,
                "kind": kind,
                "confirm_url": confirm_url,
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
        return InviteEmailResult(sent=True)

    return smtp_result



def _format_confirmation_fields(fields: dict) -> str:
    lines: list[str] = []
    for key, value in fields.items():
        if key == "bank" and isinstance(value, dict):
            for bank_key, bank_val in value.items():
                if bank_val:
                    lines.append(f"{bank_key.replace('_', ' ').title()}: {bank_val}")
            continue
        if key == "billing_address" and isinstance(value, dict):
            parts = [str(v) for v in value.values() if v]
            if parts:
                lines.append(f"Address: {', '.join(parts)}")
            continue
        if isinstance(value, list):
            if value:
                lines.append(f"{key.replace('_', ' ').title()}: {', '.join(str(v) for v in value)}")
            continue
        if value:
            lines.append(f"{key.replace('_', ' ').title()}: {value}")
    return "\n".join(lines) if lines else "No details on file yet."


async def send_master_confirmation_email(
    *,
    to_email: str,
    party_name: str,
    kind: str,
    confirm_url: str,
    fields: dict,
) -> InviteEmailResult:
    """Send vendor/employee master confirmation link."""
    settings = get_settings()
    if settings.is_production or graph_mail_send_configured():
        validate_deliverable_email_or_raise(to_email)

    label = "employee" if kind == "employee" else "vendor"
    subject = f"Please confirm your {label} details — LedgerLink"
    detail_block = _format_confirmation_fields(fields)
    body_text = (
        f"Hello {party_name},\n\n"
        f"Please review and confirm your {label} details on file:\n\n"
        f"{detail_block}\n\n"
        f"Review, edit if needed, and confirm here:\n{confirm_url}\n\n"
        "This link expires in 7 days.\n\n"
        "If you did not expect this email, you can ignore it."
    )
    body_html = (
        f"<p>Hello <strong>{party_name}</strong>,</p>"
        f"<p>Please review and confirm your {label} details on file:</p>"
        f"<pre style=\"white-space:pre-wrap;font-family:inherit\">{detail_block}</pre>"
        f'<p><a href="{confirm_url}">Review and confirm your details</a></p>'
        "<p>This link expires in 7 days.</p>"
        "<p>If you did not expect this email, you can ignore it.</p>"
    )

    if not settings.is_production:
        logger.info(
            "master_confirmation_email",
            extra={
                "email": to_email,
                "kind": kind,
                "confirm_url": confirm_url,
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
        return InviteEmailResult(sent=True)

    return smtp_result

