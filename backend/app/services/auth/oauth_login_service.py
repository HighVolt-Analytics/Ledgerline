"""Google / Microsoft OAuth for dashboard login and signup (PKCE + signed state)."""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
import jwt

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

STATE_TYP = "oauth_state"
STATE_TTL_MINUTES = 15

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

GOOGLE_LOGIN_SCOPES = ["openid", "email", "profile"]
MICROSOFT_LOGIN_SCOPES = ["openid", "profile", "email", "offline_access"]

OAuthIntent = Literal["signup", "login"]
OAuthProvider = Literal["google", "microsoft"]


@dataclass(frozen=True)
class OAuthIdentity:
    email: str
    name: str
    subject: str
    provider: OAuthProvider


@dataclass(frozen=True)
class MicrosoftPrepareResult:
    authorize_url: str
    pkce_verifier: str
    client_id: str
    redirect_uri: str
    token_url: str


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def create_oauth_state(
    *,
    intent: OAuthIntent,
    provider: OAuthProvider,
    pkce_verifier: str,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MINUTES)
    payload: dict[str, Any] = {
        "typ": STATE_TYP,
        "intent": intent,
        "provider": provider,
        "pkce": pkce_verifier,
        "exp": expire,
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def parse_oauth_state(state: str) -> dict[str, Any]:
    payload = jwt.decode(state, get_settings().jwt_secret, algorithms=["HS256"])
    if payload.get("typ") != STATE_TYP:
        raise ValueError("Invalid OAuth state")
    return payload


def _microsoft_authority() -> str:
    """Authorize/token host for Microsoft login/signup.

    Defaults to /common so users outside the High Volt Entra tenant can sign in.
    AZURE_TENANT_ID must never drive this — that GUID is only for Graph/mailbox.
    Requires a Multitenant Entra app registration (single-tenant + /common → AADSTS50194).
    """
    settings = get_settings()
    tenant = (settings.microsoft_oauth_authority_tenant or "").strip() or "common"
    if tenant.lower() in {"organizations", "consumers", "common"}:
        return f"https://login.microsoftonline.com/{tenant.lower()}"
    return f"https://login.microsoftonline.com/{tenant}"


def _microsoft_token_url() -> str:
    return f"{_microsoft_authority()}/oauth2/v2.0/token"


def google_oauth_login_configured() -> bool:
    return get_settings().google_oauth_login_configured


def microsoft_oauth_login_configured() -> bool:
    return get_settings().microsoft_oauth_login_configured


def build_google_authorize_url(*, intent: OAuthIntent, state: str, pkce_challenge: str) -> str:
    settings = get_settings()
    params = {
        "client_id": settings.google_client_id,
        "response_type": "code",
        "redirect_uri": settings.google_oauth_login_redirect_uri,
        "scope": " ".join(GOOGLE_LOGIN_SCOPES),
        "state": state,
        "code_challenge": pkce_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def build_microsoft_authorize_url(*, intent: OAuthIntent, state: str, pkce_challenge: str) -> str:
    settings = get_settings()
    params = {
        "client_id": settings.microsoft_oauth_client_id,
        "response_type": "code",
        "redirect_uri": settings.microsoft_oauth_redirect_uri,
        "scope": " ".join(MICROSOFT_LOGIN_SCOPES),
        "state": state,
        "code_challenge": pkce_challenge,
        "code_challenge_method": "S256",
        "response_mode": "query",
        "prompt": "select_account",
    }
    return f"{_microsoft_authority()}/oauth2/v2.0/authorize?{urlencode(params)}"


def prepare_google_oauth(intent: OAuthIntent) -> tuple[str, str]:
    """Returns (authorize_url, state)."""
    verifier, challenge = _pkce_pair()
    state = create_oauth_state(intent=intent, provider="google", pkce_verifier=verifier)
    url = build_google_authorize_url(intent=intent, state=state, pkce_challenge=challenge)
    return url, state


def prepare_microsoft_oauth(intent: OAuthIntent) -> MicrosoftPrepareResult:
    verifier, challenge = _pkce_pair()
    state = create_oauth_state(intent=intent, provider="microsoft", pkce_verifier=verifier)
    settings = get_settings()
    return MicrosoftPrepareResult(
        authorize_url=build_microsoft_authorize_url(
            intent=intent, state=state, pkce_challenge=challenge
        ),
        pkce_verifier=verifier,
        client_id=settings.microsoft_oauth_client_id,
        redirect_uri=settings.microsoft_oauth_redirect_uri,
        token_url=_microsoft_token_url(),
    )


def _parse_id_token_claims(id_token: str) -> dict[str, Any]:
    claims = jwt.decode(id_token, options={"verify_signature": False})
    return claims


def identity_from_id_token(*, id_token: str, provider: OAuthProvider) -> OAuthIdentity:
    claims = _parse_id_token_claims(id_token)
    if provider == "google":
        email = str(claims.get("email") or "").lower().strip()
        name = str(claims.get("name") or email.split("@")[0])
        subject = str(claims.get("sub") or "")
    else:
        email = str(claims.get("email") or claims.get("preferred_username") or "").lower().strip()
        name = str(claims.get("name") or email.split("@")[0])
        subject = str(claims.get("oid") or claims.get("sub") or "")
    if not email:
        raise ValueError("OAuth provider did not return an email address")
    return OAuthIdentity(email=email, name=name, subject=subject, provider=provider)


async def exchange_google_code(*, code: str, pkce_verifier: str) -> OAuthIdentity:
    settings = get_settings()
    data = {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "code": code,
        "redirect_uri": settings.google_oauth_login_redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": pkce_verifier,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(GOOGLE_TOKEN_URL, data=data)
        if response.is_error:
            logger.error("google_login_oauth_exchange_failed", body=response.text[:500])
            response.raise_for_status()
        token_data = response.json()
    id_token = str(token_data.get("id_token") or "")
    if not id_token:
        raise ValueError("Google token response missing id_token")
    return identity_from_id_token(id_token=id_token, provider="google")


async def exchange_microsoft_code_confidential(*, code: str, pkce_verifier: str) -> OAuthIdentity:
    settings = get_settings()
    redirect_uri = settings.microsoft_oauth_redirect_uri
    data = {
        "client_id": settings.microsoft_oauth_client_id,
        "client_secret": settings.microsoft_oauth_client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": pkce_verifier,
        "scope": " ".join(MICROSOFT_LOGIN_SCOPES),
    }
    logger.info(
        "microsoft_oauth_token_exchange_start",
        redirect_uri=redirect_uri,
        client_id_prefix=settings.microsoft_oauth_client_id[:8] if settings.microsoft_oauth_client_id else "",
        has_client_secret=bool(settings.microsoft_oauth_client_secret.strip()),
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(_microsoft_token_url(), data=data)
        if response.is_error:
            _log_microsoft_token_error(response)
            response.raise_for_status()
        token_data = response.json()
    id_token = str(token_data.get("id_token") or "")
    if not id_token:
        raise ValueError("Microsoft token response missing id_token")
    identity = identity_from_id_token(id_token=id_token, provider="microsoft")
    logger.info("microsoft_oauth_token_exchange_ok", email=identity.email)
    return identity


def _log_microsoft_token_error(response: httpx.Response) -> None:
    body = response.text[:1000]
    error_code = ""
    error_desc = ""
    try:
        payload = response.json()
        error_code = str(payload.get("error") or "")
        error_desc = str(payload.get("error_description") or payload.get("error_codes") or "")
    except Exception:
        pass
    logger.error(
        "microsoft_login_oauth_exchange_failed",
        status_code=response.status_code,
        error=error_code,
        error_description=error_desc[:500],
        body=body,
    )


def identity_from_microsoft_complete(*, id_token: str) -> OAuthIdentity:
    return identity_from_id_token(id_token=id_token, provider="microsoft")
