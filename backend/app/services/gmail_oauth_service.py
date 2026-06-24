"""Google Gmail delegated OAuth for mailbox connection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
import uuid

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.connected_mailbox import (
    AUTH_DELEGATED,
    MAIL_PROVIDER_GOOGLE,
    STATUS_CONNECTED,
    STATUS_DISCONNECTED,
    STATUS_ERROR,
    ConnectedMailbox,
)
from app.services.token_vault import decrypt_secret, encrypt_secret
from app.tenant_ids import parse_tenant_id
from app.utils.logger import get_logger

logger = get_logger(__name__)

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]
STATE_TYP = "gmail_mailbox_oauth"
STATE_TTL_MINUTES = 15
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def gmail_oauth_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.google_client_id.strip()
        and settings.google_client_secret.strip()
        and settings.gmail_oauth_redirect_uri.strip()
    )


def create_oauth_state(
    *,
    tenant_id: uuid.UUID | str | int,
    invite_request_id: int | None = None,
    user_id: int | None = None,
) -> str:
    org_id = parse_tenant_id(tenant_id)
    if org_id is None:
        raise ValueError("Invalid tenant id")
    expire = datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MINUTES)
    payload: dict[str, Any] = {
        "typ": STATE_TYP,
        "org_id": str(org_id),
        "exp": expire,
        "provider": MAIL_PROVIDER_GOOGLE,
    }
    if invite_request_id is not None:
        payload["invite_request_id"] = invite_request_id
        payload["flow"] = "invite"
    elif user_id is not None:
        payload["user_id"] = user_id
        payload["flow"] = "direct"
    else:
        raise ValueError("OAuth state requires user_id or invite_request_id")
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def parse_oauth_state(state: str) -> dict[str, Any]:
    payload = jwt.decode(state, get_settings().jwt_secret, algorithms=["HS256"])
    if payload.get("typ") != STATE_TYP:
        raise ValueError("Invalid OAuth state")
    return payload


def build_invite_authorize_url(*, tenant_id: uuid.UUID | str | int, invite_request_id: int) -> str:
    settings = get_settings()
    if not gmail_oauth_configured():
        raise RuntimeError("Google OAuth is not configured")
    state = create_oauth_state(tenant_id=tenant_id, invite_request_id=invite_request_id)
    params = {
        "client_id": settings.google_client_id,
        "response_type": "code",
        "redirect_uri": settings.gmail_oauth_redirect_uri,
        "scope": " ".join(GMAIL_SCOPES),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def _exchange_code(code: str) -> dict[str, Any]:
    settings = get_settings()
    data = {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "code": code,
        "redirect_uri": settings.gmail_oauth_redirect_uri,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(GOOGLE_TOKEN_URL, data=data)
        if response.is_error:
            logger.error("gmail_oauth_code_exchange_failed", body=response.text[:500])
            response.raise_for_status()
        return response.json()


async def _refresh_tokens(refresh_token: str) -> dict[str, Any]:
    settings = get_settings()
    data = {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(GOOGLE_TOKEN_URL, data=data)
        if response.is_error:
            logger.error("gmail_oauth_refresh_failed", body=response.text[:500])
            response.raise_for_status()
        return response.json()


async def _fetch_profile(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()


def _apply_token_response(mailbox: ConnectedMailbox, token_data: dict[str, Any]) -> None:
    access = str(token_data.get("access_token") or "")
    if not access:
        raise RuntimeError("Token response missing access_token")

    mailbox.access_token_encrypted = encrypt_secret(access)
    refresh = token_data.get("refresh_token")
    if refresh:
        mailbox.refresh_token_encrypted = encrypt_secret(str(refresh))

    expires_in = int(token_data.get("expires_in") or 3600)
    mailbox.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    mailbox.connection_status = STATUS_CONNECTED
    mailbox.last_error = None
    mailbox.auth_type = AUTH_DELEGATED
    mailbox.mail_provider = MAIL_PROVIDER_GOOGLE


async def complete_oauth_callback(
    session: AsyncSession,
    *,
    code: str,
    state: str,
) -> tuple[ConnectedMailbox, str]:
    payload = parse_oauth_state(state)
    tenant_id = parse_tenant_id(payload.get("org_id"))
    if tenant_id is None:
        raise RuntimeError("Invalid OAuth session")
    flow = str(payload.get("flow") or "direct")
    invite_request_id = payload.get("invite_request_id")
    user_id = payload.get("user_id")

    invite_row = None
    if flow == "invite":
        if invite_request_id is None:
            raise RuntimeError("Invalid invitation session")
        from app.services.mailbox_invite_service import get_invite_request

        invite_row = await get_invite_request(
            session,
            request_id=int(invite_request_id),
            tenant_id=tenant_id,
        )
    elif user_id is not None:
        from app.models.user import User

        user = await session.get(User, int(user_id))
        if not user or not user.is_active or user.tenant_id != tenant_id:
            raise RuntimeError("OAuth session invalid — sign in again")
    else:
        raise RuntimeError("Invalid OAuth session")

    token_data = await _exchange_code(code)
    access_token = str(token_data["access_token"])
    profile = await _fetch_profile(access_token)
    email = str(profile.get("email") or "").strip().lower()
    if not email:
        raise RuntimeError("Could not resolve mailbox email from Google profile")

    if invite_row is not None and email != invite_row.requested_email.lower():
        raise RuntimeError(
            f"Sign in with {invite_row.requested_email} — the invited mailbox account"
        )

    oauth_user_id = str(profile.get("sub") or "")
    display_name = str(profile.get("name") or email)
    if invite_row and invite_row.display_name:
        display_name = invite_row.display_name

    existing = (
        await session.execute(
            select(ConnectedMailbox).where(
                ConnectedMailbox.tenant_id == tenant_id,
                ConnectedMailbox.email == email,
            )
        )
    ).scalar_one_or_none()

    if existing:
        mailbox = existing
    else:
        mailbox = ConnectedMailbox(
            tenant_id=tenant_id,
            email=email,
            display_name=display_name,
            is_active=True,
            mail_provider=MAIL_PROVIDER_GOOGLE,
        )
        session.add(mailbox)

    mailbox.display_name = display_name
    mailbox.oauth_user_id = oauth_user_id or None
    mailbox.oauth_connected_at = datetime.now(timezone.utc)
    _apply_token_response(mailbox, token_data)
    await session.flush()

    if invite_row is not None:
        from app.services.mailbox_invite_service import mark_invite_connected

        await mark_invite_connected(
            session,
            request_id=invite_row.id,
            tenant_id=tenant_id,
            mailbox_id=mailbox.id,
            actor_email=email,
        )

    logger.info(
        "gmail_oauth_connected",
        mailbox=email,
        tenant_id=tenant_id,
        flow=flow,
        invite_request_id=invite_request_id,
    )
    return mailbox, flow


async def resolve_gmail_access_token(mailbox: ConnectedMailbox) -> str:
    if mailbox.mail_provider != MAIL_PROVIDER_GOOGLE:
        raise RuntimeError("Mailbox is not Gmail-connected")
    if mailbox.auth_type != AUTH_DELEGATED:
        raise RuntimeError("Mailbox is not OAuth-connected")

    access = decrypt_secret(mailbox.access_token_encrypted)
    expires_at = mailbox.token_expires_at
    if access and expires_at:
        if expires_at > datetime.now(timezone.utc) + timedelta(minutes=2):
            return access

    refresh = decrypt_secret(mailbox.refresh_token_encrypted)
    if not refresh:
        mailbox.connection_status = STATUS_DISCONNECTED
        mailbox.last_error = "Refresh token missing — reconnect mailbox"
        raise RuntimeError(mailbox.last_error)

    token_data = await _refresh_tokens(refresh)
    _apply_token_response(mailbox, token_data)
    access = decrypt_secret(mailbox.access_token_encrypted)
    if not access:
        mailbox.connection_status = STATUS_ERROR
        mailbox.last_error = "Failed to decrypt refreshed access token"
        raise RuntimeError(mailbox.last_error)
    return access
