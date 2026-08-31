"""Xero authorize/token/connections URLs and scopes."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings

PROVIDER = "xero"
OAUTH_STATE_TYP = "xero_oauth"


def is_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.xero_enabled
        and settings.xero_client_id.strip()
        and settings.xero_client_secret.strip()
    )


def resolve_scopes() -> str:
    scopes = get_settings().xero_scopes.strip()
    if not scopes:
        raise ValueError("XERO_SCOPES must be configured")
    return scopes


def authorize_url(*, state: str) -> str:
    settings = get_settings()
    params = {
        "response_type": "code",
        "client_id": settings.xero_client_id.strip(),
        "redirect_uri": settings.xero_redirect_uri.strip(),
        "scope": resolve_scopes(),
        "state": state,
    }
    return f"{settings.xero_authorize_url}?{urlencode(params)}"


def token_url() -> str:
    return get_settings().xero_token_url


def connections_url() -> str:
    return get_settings().xero_connections_url


async def exchange_authorization_code(code: str) -> dict[str, Any]:
    """POST identity token + GET /connections. Does not touch the database."""
    settings = get_settings()
    auth = base64.b64encode(
        f"{settings.xero_client_id.strip()}:{settings.xero_client_secret.strip()}".encode()
    ).decode("ascii")
    async with httpx.AsyncClient(timeout=30.0) as client:
        token_resp = await client.post(
            token_url(),
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.xero_redirect_uri.strip(),
            },
        )
        if token_resp.status_code >= 400:
            raise RuntimeError("Xero token exchange failed")
        token_data = token_resp.json()
        access_token = str(token_data.get("access_token") or "")
        if not access_token:
            raise RuntimeError("Xero token exchange returned no access token")
        refresh_token = token_data.get("refresh_token")
        expires_in = int(token_data.get("expires_in") or 0)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            if expires_in > 0
            else None
        )
        connections_resp = await client.get(
            connections_url(),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        if connections_resp.status_code >= 400:
            raise RuntimeError("Failed to load Xero organisation connections")
        connections = connections_resp.json()
        if not connections:
            raise RuntimeError("No Xero organisations available for this account")

    return {
        "access_token": access_token,
        "refresh_token": str(refresh_token) if refresh_token else None,
        "expires_at": expires_at,
        "scopes": token_data.get("scope") or resolve_scopes(),
        "connections": connections,
    }
