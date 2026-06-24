"""Admin-initiated mailbox connection invites (email → OAuth consent)."""

from __future__ import annotations

import smtplib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.mailbox_connection_request import (
    STATUS_CONNECTED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    MailboxConnectionRequest,
)
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit_service import log_event
from app.services.graph_mail_sender import graph_mail_send_configured, send_graph_mail
from app.services.mailbox_provider import (
    PROVIDER_GOOGLE,
    PROVIDER_MICROSOFT,
    PROVIDER_UNKNOWN,
    available_providers_for_email,
    detect_mailbox_provider,
    resolve_invite_provider,
)
from app.services.public_app_url import build_public_app_path
from app.tenant_ids import parse_tenant_id
from app.utils.logger import get_logger

logger = get_logger(__name__)

INVITE_TYP = "mailbox_invite"
INVITE_TTL_DAYS = 7


@dataclass(frozen=True)
class InviteEmailResult:
    sent: bool
    error: str | None = None


@dataclass(frozen=True)
class InviteActionResult:
    row: MailboxConnectionRequest
    connect_url: str
    email_sent: bool
    email_error: str | None = None


def create_invite_token(*, request_id: int, tenant_id: uuid.UUID | str | int) -> str:
    org_id = parse_tenant_id(tenant_id)
    if org_id is None:
        raise ValueError("Invalid tenant id")
    expire = datetime.now(timezone.utc) + timedelta(days=INVITE_TTL_DAYS)
    payload = {
        "typ": INVITE_TYP,
        "request_id": request_id,
        "org_id": str(org_id),
        "exp": expire,
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def parse_invite_token(token: str) -> dict[str, int | uuid.UUID]:
    payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    if payload.get("typ") != INVITE_TYP:
        raise ValueError("Invalid invite token")
    org_id = parse_tenant_id(payload.get("org_id"))
    if org_id is None:
        raise ValueError("Invalid invite token")
    return {
        "request_id": int(payload["request_id"]),
        "org_id": org_id,
    }


def invite_connect_url(token: str) -> str:
    from urllib.parse import urlencode

    return build_public_app_path(f"/connect-mailbox?{urlencode({'token': token})}")


def build_connect_url_for_request(*, request_id: int, tenant_id: uuid.UUID | str | int) -> str:
    token = create_invite_token(request_id=request_id, tenant_id=tenant_id)
    return invite_connect_url(token)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_expired(row: MailboxConnectionRequest) -> bool:
    if row.status != STATUS_PENDING:
        return row.status == STATUS_EXPIRED
    if row.expires_at is None:
        return False
    return _as_utc_aware(row.expires_at) <= _utc_now()


async def get_invite_request(
    session: AsyncSession,
    *,
    request_id: int,
    tenant_id: uuid.UUID | str | int | None = None,
) -> MailboxConnectionRequest:
    row = await session.get(MailboxConnectionRequest, request_id)
    if not row:
        raise ValueError("Invitation not found")
    if tenant_id is not None:
        expected = parse_tenant_id(tenant_id)
        if expected is None or row.tenant_id != expected:
            raise ValueError("Invitation not found")
    if _is_expired(row) and row.status == STATUS_PENDING:
        row.status = STATUS_EXPIRED
        await session.flush()
    if row.status != STATUS_PENDING:
        raise ValueError(f"Invitation is {row.status}")
    return row


async def load_invite_for_token(
    session: AsyncSession,
    token: str,
) -> tuple[MailboxConnectionRequest, Tenant]:
    ids = parse_invite_token(token)
    row = await get_invite_request(
        session,
        request_id=ids["request_id"],
        tenant_id=ids["org_id"],
    )
    org = await session.get(Tenant, row.tenant_id)
    if not org:
        raise ValueError("Tenant not found")
    return row, org


def send_invite_email(
    *,
    to_email: str,
    tenant_name: str,
    requested_email: str,
    connect_url: str,
    personal_message: str | None,
    expires_at: datetime,
) -> InviteEmailResult:
    settings = get_settings()
    subject = f"{tenant_name} — connect your mailbox to LedgerLink"
    expiry_label = expires_at.astimezone(timezone.utc).strftime("%d %b %Y")

    body_text = (
        f"Hello,\n\n"
        f"{tenant_name} has requested permission to read invoice attachments from "
        f"{requested_email} using LedgerLink.\n\n"
    )
    if personal_message and personal_message.strip():
        body_text += f"Message from your team:\n{personal_message.strip()}\n\n"
    body_text += (
        f"Open this link to review and connect your mailbox:\n{connect_url}\n\n"
        f"This invitation expires on {expiry_label}.\n\n"
        f"If you did not expect this email, you can ignore it.\n"
    )

    html = (
        f"<p>Hello,</p>"
        f"<p><strong>{tenant_name}</strong> has requested permission to read invoice "
        f"attachments from <strong>{requested_email}</strong> using LedgerLink.</p>"
    )
    if personal_message and personal_message.strip():
        html += f"<p><em>{personal_message.strip()}</em></p>"
    html += (
        f'<p><a href="{connect_url}">Connect my mailbox</a></p>'
        f"<p>This invitation expires on {expiry_label}.</p>"
        f"<p>If you did not expect this email, you can ignore it.</p>"
    )

    if graph_mail_send_configured():
        graph_result = send_graph_mail(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=html,
        )
        if graph_result.sent:
            return InviteEmailResult(sent=True)
        return InviteEmailResult(sent=False, error=graph_result.error)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.send_message(msg)
        return InviteEmailResult(sent=True)
    except OSError as exc:
        logger.warning(
            "mailbox_invite_email_failed",
            to=to_email,
            error=str(exc),
        )
        return InviteEmailResult(
            sent=False,
            error=f"SMTP failed ({settings.smtp_host}:{settings.smtp_port}).",
        )


async def create_mailbox_connection_request(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    requested_email: str,
    display_name: str | None,
    message: str | None,
    requested_by_user_id: int,
    actor_name: str | None = None,
    actor_email: str | None = None,
) -> InviteActionResult:
    email = requested_email.strip().lower()
    if not email:
        raise ValueError("Email is required")

    pending = (
        await session.execute(
            select(MailboxConnectionRequest).where(
                MailboxConnectionRequest.tenant_id == tenant_id,
                MailboxConnectionRequest.requested_email == email,
                MailboxConnectionRequest.status == STATUS_PENDING,
            )
        )
    ).scalar_one_or_none()
    if pending and not _is_expired(pending):
        if display_name is not None:
            pending.display_name = (display_name or "").strip() or None
        if message is not None:
            pending.message = (message or "").strip() or None
        detected = detect_mailbox_provider(email)
        if detected != PROVIDER_UNKNOWN:
            pending.mail_provider = detected
        return await resend_mailbox_connection_request(
            session,
            request_id=pending.id,
            tenant_id=tenant_id,
            actor_name=actor_name,
            actor_email=actor_email,
        )

    org = await session.get(Tenant, tenant_id)
    tenant_name = org.name if org else "Your organisation"
    detected_provider = detect_mailbox_provider(email)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=INVITE_TTL_DAYS)

    row = MailboxConnectionRequest(
        tenant_id=tenant_id,
        requested_email=email,
        display_name=(display_name or "").strip() or None,
        message=(message or "").strip() or None,
        mail_provider=detected_provider if detected_provider != PROVIDER_UNKNOWN else None,
        status=STATUS_PENDING,
        requested_by_user_id=requested_by_user_id,
        invite_sent_at=now,
        expires_at=expires_at,
    )
    session.add(row)
    await session.flush()

    token = create_invite_token(request_id=row.id, tenant_id=tenant_id)
    url = invite_connect_url(token)
    delivery = send_invite_email(
        to_email=email,
        tenant_name=tenant_name,
        requested_email=email,
        connect_url=url,
        personal_message=message,
        expires_at=expires_at,
    )

    await log_event(
        session,
        "mailbox_connect_requested",
        tenant_id=tenant_id,
        detail={
            "request_id": row.id,
            "requested_email": email,
            "expires_at": expires_at.isoformat(),
            "email_sent": delivery.sent,
        },
        actor_name=actor_name,
        actor_email=actor_email,
    )
    await session.flush()
    return InviteActionResult(
        row=row,
        connect_url=url,
        email_sent=delivery.sent,
        email_error=delivery.error,
    )


async def resend_mailbox_connection_request(
    session: AsyncSession,
    *,
    request_id: int,
    tenant_id: uuid.UUID,
    actor_name: str | None = None,
    actor_email: str | None = None,
) -> InviteActionResult:
    row = await get_invite_request(session, request_id=request_id, tenant_id=tenant_id)
    org = await session.get(Tenant, tenant_id)
    tenant_name = org.name if org else "Your organisation"
    now = datetime.now(timezone.utc)
    row.expires_at = now + timedelta(days=INVITE_TTL_DAYS)
    row.invite_sent_at = now
    await session.flush()

    token = create_invite_token(request_id=row.id, tenant_id=tenant_id)
    url = invite_connect_url(token)
    delivery = send_invite_email(
        to_email=row.requested_email,
        tenant_name=tenant_name,
        requested_email=row.requested_email,
        connect_url=url,
        personal_message=row.message,
        expires_at=row.expires_at,
    )

    await log_event(
        session,
        "mailbox_connect_resent",
        tenant_id=tenant_id,
        detail={
            "request_id": row.id,
            "requested_email": row.requested_email,
            "email_sent": delivery.sent,
        },
        actor_name=actor_name,
        actor_email=actor_email,
    )
    await session.flush()
    return InviteActionResult(
        row=row,
        connect_url=url,
        email_sent=delivery.sent,
        email_error=delivery.error,
    )


def build_invite_oauth_url(
    *,
    tenant_id: uuid.UUID,
    invite_request_id: int,
    requested_email: str,
    stored_provider: str | None,
    provider: str | None = None,
) -> str:
    from app.services import gmail_oauth_service, mailbox_oauth_service

    resolved = resolve_invite_provider(
        requested_email,
        stored=stored_provider,
        requested=provider,
    )
    if resolved == PROVIDER_GOOGLE:
        if not gmail_oauth_service.gmail_oauth_configured():
            raise RuntimeError(
                "Google OAuth is not configured. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, "
                "and GMAIL_OAUTH_REDIRECT_URI."
            )
        return gmail_oauth_service.build_invite_authorize_url(
            tenant_id=tenant_id,
            invite_request_id=invite_request_id,
        )
    if not mailbox_oauth_service.oauth_configured():
        raise RuntimeError(
            "Microsoft OAuth is not configured. Set AZURE_TENANT_ID, AZURE_CLIENT_ID, "
            "AZURE_CLIENT_SECRET, and GRAPH_OAUTH_REDIRECT_URI."
        )
    return mailbox_oauth_service.build_invite_authorize_url(
        tenant_id=tenant_id,
        invite_request_id=invite_request_id,
    )


async def mark_invite_connected(
    session: AsyncSession,
    *,
    request_id: int,
    tenant_id: uuid.UUID,
    mailbox_id: int,
    actor_email: str | None = None,
) -> None:
    row = await session.get(MailboxConnectionRequest, request_id)
    if not row or row.tenant_id != tenant_id:
        return
    row.status = STATUS_CONNECTED
    row.connected_mailbox_id = mailbox_id
    row.connected_at = datetime.now(timezone.utc)
    await log_event(
        session,
        "mailbox_connect_completed",
        tenant_id=tenant_id,
        detail={
            "request_id": row.id,
            "requested_email": row.requested_email,
            "mailbox_id": mailbox_id,
        },
        actor_email=actor_email,
    )
    await session.flush()
