"""Microsoft 365 delegated OAuth for mailbox connection (authorization code flow)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.connected_mailbox import (
    AUTH_APPLICATION,
    AUTH_DELEGATED,
    STATUS_CONNECTED,
    STATUS_DISCONNECTED,
    STATUS_ERROR,
    ConnectedMailbox,
)
from app.services.token_vault import decrypt_secret, encrypt_secret
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Delegated permissions — user consent in Microsoft login (Mail.ReadWrite includes read).
GRAPH_DELEGATED_SCOPES = [
    "https://graph.microsoft.com/Mail.ReadWrite",
    "https://graph.microsoft.com/User.Read",
    "offline_access",
    "openid",
    "profile",
]

STATE_TYP = "mailbox_oauth"
STATE_TTL_MINUTES = 15


def oauth_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.azure_tenant_id.strip()
        and settings.azure_client_id.strip()
        and settings.azure_client_secret.strip()
        and settings.graph_oauth_redirect_uri.strip()
    )


def _authority() -> str:
    return f"https://login.microsoftonline.com/{get_settings().azure_tenant_id}"


def create_oauth_state(
    *,
    org_id: int,
    user_id: int | None = None,
    invite_request_id: int | None = None,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MINUTES)
    payload: dict[str, Any] = {
        "typ": STATE_TYP,
        "org_id": org_id,
        "exp": expire,
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


def build_authorize_url(*, org_id: int, user_id: int) -> str:
    return _build_authorize_url(
        org_id=org_id,
        state=create_oauth_state(org_id=org_id, user_id=user_id),
    )


def build_invite_authorize_url(*, org_id: int, invite_request_id: int) -> str:
    return _build_authorize_url(
        org_id=org_id,
        state=create_oauth_state(org_id=org_id, invite_request_id=invite_request_id),
    )


def build_admin_consent_url() -> str:
    """One-time org-wide consent URL for a Global Admin (fixes 'Need admin approval')."""
    settings = get_settings()
    if not settings.azure_tenant_id.strip() or not settings.azure_client_id.strip():
        raise RuntimeError("Microsoft OAuth is not configured")
    params = {
        "client_id": settings.azure_client_id,
        "scope": " ".join(GRAPH_DELEGATED_SCOPES),
    }
    redirect = settings.graph_oauth_redirect_uri.strip()
    if redirect:
        params["redirect_uri"] = redirect
    return f"{_authority()}/v2.0/adminconsent?{urlencode(params)}"


def _build_authorize_url(*, org_id: int, state: str) -> str:
    settings = get_settings()
    if not oauth_configured():
        raise RuntimeError("Microsoft OAuth is not configured")

    params = {
        "client_id": settings.azure_client_id,
        "response_type": "code",
        "redirect_uri": settings.graph_oauth_redirect_uri,
        "response_mode": "query",
        "scope": " ".join(GRAPH_DELEGATED_SCOPES),
        "state": state,
        # select_account — after IT grants admin consent once, users sign in without
        # re-triggering the "Need admin approval" wall that prompt=consent can show.
        "prompt": "select_account",
    }
    return f"{_authority()}/oauth2/v2.0/authorize?{urlencode(params)}"


def _token_endpoint() -> str:
    return f"{_authority()}/oauth2/v2.0/token"


async def _exchange_code(code: str) -> dict[str, Any]:
    settings = get_settings()
    data = {
        "client_id": settings.azure_client_id,
        "client_secret": settings.azure_client_secret,
        "code": code,
        "redirect_uri": settings.graph_oauth_redirect_uri,
        "grant_type": "authorization_code",
        "scope": " ".join(GRAPH_DELEGATED_SCOPES),
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(_token_endpoint(), data=data)
        if response.is_error:
            logger.error("oauth_code_exchange_failed", body=response.text[:500])
            response.raise_for_status()
        return response.json()


async def _refresh_tokens(refresh_token: str) -> dict[str, Any]:
    settings = get_settings()
    data = {
        "client_id": settings.azure_client_id,
        "client_secret": settings.azure_client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "scope": " ".join(GRAPH_DELEGATED_SCOPES),
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(_token_endpoint(), data=data)
        if response.is_error:
            logger.error("oauth_refresh_failed", body=response.text[:500])
            response.raise_for_status()
        return response.json()


async def _fetch_graph_profile(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"$select": "id,mail,userPrincipalName,displayName"},
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


async def complete_oauth_callback(
    session: AsyncSession,
    *,
    code: str,
    state: str,
) -> tuple[ConnectedMailbox, str]:
    """Exchange auth code, upsert connected mailbox. Returns (mailbox, flow)."""
    payload = parse_oauth_state(state)
    org_id = int(payload["org_id"])
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
            org_id=org_id,
        )
    elif user_id is not None:
        from app.models.user import User

        user = await session.get(User, int(user_id))
        if not user or not user.is_active or user.org_id != org_id:
            raise RuntimeError("OAuth session invalid — sign in again")
    else:
        raise RuntimeError("Invalid OAuth session")

    token_data = await _exchange_code(code)
    access_token = str(token_data["access_token"])
    profile = await _fetch_graph_profile(access_token)

    email = (
        str(profile.get("mail") or profile.get("userPrincipalName") or "")
        .strip()
        .lower()
    )
    if not email:
        raise RuntimeError("Could not resolve mailbox email from Microsoft profile")

    if invite_row is not None and email != invite_row.requested_email.lower():
        raise RuntimeError(
            f"Sign in with {invite_row.requested_email} — the invited mailbox account"
        )

    oauth_user_id = str(profile.get("id") or "")
    display_name = str(profile.get("displayName") or email)
    if invite_row and invite_row.display_name:
        display_name = invite_row.display_name

    existing = (
        await session.execute(
            select(ConnectedMailbox).where(
                ConnectedMailbox.org_id == org_id,
                ConnectedMailbox.email == email,
            )
        )
    ).scalar_one_or_none()

    if existing:
        mailbox = existing
    else:
        mailbox = ConnectedMailbox(
            org_id=org_id,
            email=email,
            display_name=display_name,
            is_active=True,
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
            org_id=org_id,
            mailbox_id=mailbox.id,
            actor_email=email,
        )

    logger.info(
        "mailbox_oauth_connected",
        mailbox=email,
        org_id=org_id,
        flow=flow,
        invite_request_id=invite_request_id,
    )
    return mailbox, flow


async def resolve_delegated_access_token(mailbox: ConnectedMailbox) -> str:
    """Return a valid delegated access token, refreshing when needed."""
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


async def resolve_mailbox_access_token(
    session: AsyncSession,
    mailbox: ConnectedMailbox,
) -> str:
    """Delegated token for OAuth mailboxes; application token for service mailboxes."""
    from app.services.graph_client import get_application_access_token

    if mailbox.auth_type == AUTH_DELEGATED:
        row = mailbox
        try:
            row = (
                await session.execute(
                    select(ConnectedMailbox)
                    .where(ConnectedMailbox.id == mailbox.id)
                    .with_for_update()
                )
            ).scalar_one()
            token = await resolve_delegated_access_token(row)
            await session.flush()
            return token
        except Exception as exc:
            row.connection_status = STATUS_ERROR
            row.last_error = str(exc)[:500]
            await session.flush()
            raise

    if mailbox.auth_type == AUTH_APPLICATION:
        return get_application_access_token()

    raise RuntimeError(f"Unsupported mailbox auth_type: {mailbox.auth_type}")


def mark_application_mailbox(mailbox: ConnectedMailbox) -> None:
    mailbox.auth_type = AUTH_APPLICATION
    mailbox.connection_status = STATUS_CONNECTED
    mailbox.access_token_encrypted = None
    mailbox.refresh_token_encrypted = None
    mailbox.token_expires_at = None
    mailbox.oauth_user_id = None
    mailbox.oauth_connected_at = None
    mailbox.last_error = None


def disconnect_oauth_mailbox(mailbox: ConnectedMailbox) -> None:
    mailbox.connection_status = STATUS_DISCONNECTED
    mailbox.access_token_encrypted = None
    mailbox.refresh_token_encrypted = None
    mailbox.token_expires_at = None
    mailbox.last_error = None
    mailbox.is_active = False
