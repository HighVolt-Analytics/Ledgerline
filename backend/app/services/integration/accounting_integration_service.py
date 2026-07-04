"""OAuth connect/disconnect for Xero and QuickBooks Online — no accounting writes yet."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.accounting_integration import (
    AccountingIntegration,
    AccountingIntegrationStatus,
    AccountingProvider,
)
from app.services.shared.token_vault import decrypt_secret, encrypt_secret
from app.tenant_ids import parse_tenant_id
from app.utils.logger import get_logger

logger = get_logger(__name__)

STATE_TTL_MINUTES = 20
XERO_STATE_TYP = "xero_oauth"
QBO_STATE_TYP = "quickbooks_oauth"

XERO_AUTHORIZE_URL = "https://login.xero.com/identity/connect/authorize"
XERO_TOKEN_URL = "https://identity.xero.com/connect/token"
XERO_CONNECTIONS_URL = "https://api.xero.com/connections"

QBO_AUTHORIZE_URL = "https://appcenter.intuit.com/connect/oauth2"
QBO_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

_PROVIDER_LABELS = {
    AccountingProvider.XERO.value: "Xero",
    AccountingProvider.QUICKBOOKS_ONLINE.value: "QuickBooks Online",
}


def xero_configured() -> bool:
    settings = get_settings()
    return bool(settings.xero_client_id.strip() and settings.xero_client_secret.strip())


def quickbooks_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.quickbooks_client_id.strip() and settings.quickbooks_client_secret.strip()
    )


def provider_configured(provider: str) -> bool:
    if provider == AccountingProvider.XERO.value:
        return xero_configured()
    if provider == AccountingProvider.QUICKBOOKS_ONLINE.value:
        return quickbooks_configured()
    return False


def _state_typ_for_provider(provider: str) -> str:
    if provider == AccountingProvider.XERO.value:
        return XERO_STATE_TYP
    if provider == AccountingProvider.QUICKBOOKS_ONLINE.value:
        return QBO_STATE_TYP
    raise ValueError(f"Unsupported provider: {provider}")


def create_oauth_state(
    *,
    provider: str,
    tenant_id: uuid.UUID | str,
    user_id: int,
) -> str:
    org_id = parse_tenant_id(tenant_id)
    if org_id is None:
        raise ValueError("Invalid tenant id")
    expire = datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MINUTES)
    payload: dict[str, Any] = {
        "typ": _state_typ_for_provider(provider),
        "provider": provider,
        "org_id": str(org_id),
        "sub": str(user_id),
        "exp": expire,
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def parse_oauth_state(state: str, *, provider: str) -> dict[str, Any]:
    payload = jwt.decode(state, get_settings().jwt_secret, algorithms=["HS256"])
    if payload.get("typ") != _state_typ_for_provider(provider):
        raise ValueError("Invalid OAuth state")
    if payload.get("provider") != provider:
        raise ValueError("OAuth state provider mismatch")
    return payload


def build_xero_authorize_url(*, state: str) -> str:
    settings = get_settings()
    params = {
        "response_type": "code",
        "client_id": settings.xero_client_id.strip(),
        "redirect_uri": settings.xero_redirect_uri.strip(),
        "scope": settings.xero_oauth_scopes,
        "state": state,
    }
    return f"{XERO_AUTHORIZE_URL}?{urlencode(params)}"


def build_quickbooks_authorize_url(*, state: str) -> str:
    settings = get_settings()
    params = {
        "client_id": settings.quickbooks_client_id.strip(),
        "redirect_uri": settings.quickbooks_redirect_uri.strip(),
        "response_type": "code",
        "scope": settings.quickbooks_oauth_scopes,
        "state": state,
    }
    return f"{QBO_AUTHORIZE_URL}?{urlencode(params)}"


def build_connect_url(*, provider: str, tenant_id: uuid.UUID, user_id: int) -> str:
    state = create_oauth_state(provider=provider, tenant_id=tenant_id, user_id=user_id)
    if provider == AccountingProvider.XERO.value:
        return build_xero_authorize_url(state=state)
    if provider == AccountingProvider.QUICKBOOKS_ONLINE.value:
        return build_quickbooks_authorize_url(state=state)
    raise ValueError(f"Unsupported provider: {provider}")


async def get_integration(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    provider: str,
) -> AccountingIntegration | None:
    return (
        await db.execute(
            select(AccountingIntegration).where(
                AccountingIntegration.tenant_id == tenant_id,
                AccountingIntegration.provider == provider,
            )
        )
    ).scalar_one_or_none()


async def list_integrations(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[AccountingIntegration]:
    rows = (
        await db.execute(
            select(AccountingIntegration).where(AccountingIntegration.tenant_id == tenant_id)
        )
    ).scalars().all()
    return list(rows)


def integration_status_item(
    provider: str,
    row: AccountingIntegration | None,
) -> dict[str, Any]:
    configured = provider_configured(provider)
    if row is None:
        return {
            "provider": provider,
            "configured": configured,
            "status": AccountingIntegrationStatus.DISCONNECTED.value,
            "display_name": None,
            "provider_tenant_id": None,
            "scopes": None,
            "connected_at": None,
            "last_error": None,
        }
    return {
        "provider": provider,
        "configured": configured,
        "status": row.status,
        "display_name": row.display_name,
        "provider_tenant_id": row.provider_tenant_id,
        "scopes": row.scopes,
        "connected_at": row.connected_at,
        "last_error": row.last_error,
    }


async def disconnect_integration(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    provider: str,
) -> AccountingIntegration | None:
    row = await get_integration(db, tenant_id, provider)
    if row is None:
        return None
    row.status = AccountingIntegrationStatus.DISCONNECTED.value
    row.access_token_encrypted = None
    row.refresh_token_encrypted = None
    row.expires_at = None
    row.last_error = None
    await db.flush()
    return row


async def _upsert_integration(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    provider: str,
    user_id: int,
    provider_tenant_id: str,
    display_name: str,
    access_token: str,
    refresh_token: str | None,
    expires_at: datetime | None,
    scopes: str | None,
) -> AccountingIntegration:
    row = await get_integration(db, tenant_id, provider)
    now = datetime.now(timezone.utc)
    if row is None:
        row = AccountingIntegration(
            tenant_id=tenant_id,
            provider=provider,
        )
        db.add(row)
    row.status = AccountingIntegrationStatus.CONNECTED.value
    row.provider_tenant_id = provider_tenant_id
    row.display_name = display_name
    row.access_token_encrypted = encrypt_secret(access_token)
    row.refresh_token_encrypted = encrypt_secret(refresh_token) if refresh_token else None
    row.expires_at = expires_at
    row.scopes = scopes
    row.connected_by_user_id = user_id
    row.connected_at = now
    row.last_error = None
    await db.flush()
    return row


async def _mark_integration_error(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    provider: str,
    message: str,
) -> AccountingIntegration | None:
    row = await get_integration(db, tenant_id, provider)
    if row is None:
        row = AccountingIntegration(tenant_id=tenant_id, provider=provider)
        db.add(row)
    row.status = AccountingIntegrationStatus.ERROR.value
    row.last_error = message[:512]
    await db.flush()
    return row


async def _exchange_xero_code(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: int,
    code: str,
) -> AccountingIntegration:
    settings = get_settings()
    auth = base64.b64encode(
        f"{settings.xero_client_id.strip()}:{settings.xero_client_secret.strip()}".encode()
    ).decode("ascii")
    async with httpx.AsyncClient(timeout=30.0) as client:
        token_resp = await client.post(
            XERO_TOKEN_URL,
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
        scopes = token_data.get("scope")

        connections_resp = await client.get(
            XERO_CONNECTIONS_URL,
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
        org = connections[0]
        provider_tenant_id = str(org.get("tenantId") or "")
        display_name = str(org.get("tenantName") or provider_tenant_id or "Xero organisation")
        if not provider_tenant_id:
            raise RuntimeError("Xero organisation id missing from connections response")

    return await _upsert_integration(
        db,
        tenant_id=tenant_id,
        provider=AccountingProvider.XERO.value,
        user_id=user_id,
        provider_tenant_id=provider_tenant_id,
        display_name=display_name,
        access_token=access_token,
        refresh_token=str(refresh_token) if refresh_token else None,
        expires_at=expires_at,
        scopes=str(scopes) if scopes else settings.xero_oauth_scopes,
    )


def _quickbooks_api_base() -> str:
    settings = get_settings()
    if settings.quickbooks_sandbox_mode:
        return "https://sandbox-quickbooks.api.intuit.com"
    return "https://quickbooks.api.intuit.com"


async def _fetch_quickbooks_company_name(
    *,
    access_token: str,
    realm_id: str,
) -> str:
    url = f"{_quickbooks_api_base()}/v3/company/{realm_id}/companyinfo/{realm_id}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        if resp.status_code >= 400:
            return f"QuickBooks company {realm_id}"
        payload = resp.json()
        company = payload.get("CompanyInfo") or {}
        name = company.get("CompanyName") or company.get("LegalName")
        return str(name or f"QuickBooks company {realm_id}")


async def _exchange_quickbooks_code(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: int,
    code: str,
    realm_id: str,
) -> AccountingIntegration:
    if not realm_id:
        raise RuntimeError("QuickBooks realm id missing from callback")
    settings = get_settings()
    auth = base64.b64encode(
        f"{settings.quickbooks_client_id.strip()}:{settings.quickbooks_client_secret.strip()}".encode()
    ).decode("ascii")
    async with httpx.AsyncClient(timeout=30.0) as client:
        token_resp = await client.post(
            QBO_TOKEN_URL,
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.quickbooks_redirect_uri.strip(),
            },
        )
        if token_resp.status_code >= 400:
            raise RuntimeError("QuickBooks token exchange failed")
        token_data = token_resp.json()
        access_token = str(token_data.get("access_token") or "")
        if not access_token:
            raise RuntimeError("QuickBooks token exchange returned no access token")
        refresh_token = token_data.get("refresh_token")
        expires_in = int(token_data.get("expires_in") or 0)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            if expires_in > 0
            else None
        )
        scopes = token_data.get("scope") or settings.quickbooks_oauth_scopes

    display_name = await _fetch_quickbooks_company_name(
        access_token=access_token,
        realm_id=realm_id,
    )

    return await _upsert_integration(
        db,
        tenant_id=tenant_id,
        provider=AccountingProvider.QUICKBOOKS_ONLINE.value,
        user_id=user_id,
        provider_tenant_id=realm_id,
        display_name=display_name,
        access_token=access_token,
        refresh_token=str(refresh_token) if refresh_token else None,
        expires_at=expires_at,
        scopes=str(scopes) if scopes else None,
    )


async def complete_oauth_callback(
    db: AsyncSession,
    *,
    provider: str,
    code: str,
    tenant_id: uuid.UUID,
    user_id: int,
    realm_id: str | None = None,
) -> AccountingIntegration:
    if provider == AccountingProvider.XERO.value:
        return await _exchange_xero_code(db, tenant_id=tenant_id, user_id=user_id, code=code)
    if provider == AccountingProvider.QUICKBOOKS_ONLINE.value:
        return await _exchange_quickbooks_code(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            code=code,
            realm_id=realm_id or "",
        )
    raise ValueError(f"Unsupported provider: {provider}")


async def record_integration_error(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    provider: str,
    message: str,
) -> None:
    await _mark_integration_error(db, tenant_id=tenant_id, provider=provider, message=message)


def provider_label(provider: str) -> str:
    return _PROVIDER_LABELS.get(provider, provider)
