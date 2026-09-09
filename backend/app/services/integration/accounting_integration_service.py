"""OAuth connect/disconnect for Xero and QuickBooks Online."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.accounting_integration import (
    AccountingIntegration,
    AccountingIntegrationStatus,
    AccountingProvider,
)
from app.models.xero_connection import XeroConnection

from app.integrations.core.oauth_state import STATE_TTL_SECONDS, consume_oauth_jti
from app.integrations.xero.store import XeroNotReadyError as XeroNotReadyError
from app.integrations.xero.store import require_xero_ready as require_xero_ready
from app.services.shared.token_vault import decrypt_secret, encrypt_secret
from app.tenant_ids import parse_tenant_id
from app.utils.logger import get_logger

logger = get_logger(__name__)

STATE_TTL_MINUTES = 20
XERO_STATE_TYP = "xero_oauth"
QBO_STATE_TYP = "quickbooks_oauth"
XERO_ORGANISATION_TYPE = "ORGANISATION"

QBO_AUTHORIZE_URL = "https://appcenter.intuit.com/connect/oauth2"
QBO_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

_PROVIDER_LABELS = {
    AccountingProvider.XERO.value: "Xero",
    AccountingProvider.QUICKBOOKS_ONLINE.value: "QuickBooks Online",
}


def xero_configured() -> bool:
    return get_settings().xero_configured


def resolve_xero_scopes() -> str:
    scopes = get_settings().xero_scopes_resolved
    if not scopes:
        raise ValueError("XERO_SCOPES must be configured")
    return scopes


def quickbooks_configured() -> bool:
    return get_settings().quickbooks_configured


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
        "jti": str(uuid.uuid4()),
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


async def validate_oauth_state_replay(state_payload: dict[str, Any]) -> None:
    jti = str(state_payload.get("jti") or "")
    if not jti:
        raise ValueError("OAuth state missing replay guard")
    if not await consume_oauth_jti(jti, ttl_seconds=STATE_TTL_SECONDS):
        raise ValueError("OAuth state already used")


def build_xero_authorize_url(*, state: str) -> str:
    # STAGE 2: original URL builder commented — use app.integrations.xero.oauth.authorize_url
    from app.integrations.xero.oauth import authorize_url

    return authorize_url(state=state)


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


async def _list_xero_connection_rows(
    db: AsyncSession,
    integration_id: int,
) -> list[XeroConnection]:
    rows = (
        await db.execute(
            select(XeroConnection)
            .where(
                XeroConnection.accounting_integration_id == integration_id,
                XeroConnection.active.is_(True),
            )
            .order_by(XeroConnection.xero_tenant_name.asc())
        )
    ).scalars().all()
    return list(rows)


def _connection_item(row: XeroConnection) -> dict[str, Any]:
    return {
        "id": row.id,
        "xero_connection_id": row.xero_connection_id,
        "xero_tenant_id": row.xero_tenant_id,
        "xero_tenant_type": row.xero_tenant_type,
        "xero_tenant_name": row.xero_tenant_name,
        "selected": row.selected,
    }


async def list_xero_connections(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[dict[str, Any]]:
    integration = await get_integration(db, tenant_id, AccountingProvider.XERO.value)
    if integration is None:
        return []
    rows = await _list_xero_connection_rows(db, integration.id)
    return [_connection_item(row) for row in rows]


async def get_xero_readiness(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    integration = await get_integration(db, tenant_id, AccountingProvider.XERO.value)
    configured = xero_configured()
    if integration is None:
        return {
            "configured": configured,
            "connected": False,
            "ready": False,
            "status": AccountingIntegrationStatus.DISCONNECTED.value,
            "organisation_selected": False,
            "provider_tenant_id": None,
            "display_name": None,
            "connection_count": 0,
            "last_error": None,
        }

    connections = await _list_xero_connection_rows(db, integration.id)
    organisation_connections = [
        c for c in connections if (c.xero_tenant_type or "").upper() == XERO_ORGANISATION_TYPE
    ]
    selected = any(c.selected for c in organisation_connections)
    ready = (
        configured
        and integration.status == AccountingIntegrationStatus.CONNECTED.value
        and bool(integration.provider_tenant_id)
        and selected
        and bool(integration.access_token_encrypted)
    )
    return {
        "configured": configured,
        "connected": integration.status
        in {
            AccountingIntegrationStatus.CONNECTED.value,
            AccountingIntegrationStatus.ORGANISATION_SELECTION_REQUIRED.value,
        },
        "ready": ready,
        "status": integration.status,
        "organisation_selected": selected,
        "provider_tenant_id": integration.provider_tenant_id,
        "display_name": integration.display_name,
        "connection_count": len(organisation_connections),
        "last_error": integration.last_error,
    }


async def select_xero_connection(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    xero_connection_id: str,
) -> AccountingIntegration:
    integration = await get_integration(db, tenant_id, AccountingProvider.XERO.value)
    if integration is None:
        raise ValueError("Xero is not connected")

    row = (
        await db.execute(
            select(XeroConnection).where(
                XeroConnection.tenant_id == tenant_id,
                XeroConnection.accounting_integration_id == integration.id,
                XeroConnection.xero_connection_id == xero_connection_id,
                XeroConnection.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError("Xero connection not found")
    if (row.xero_tenant_type or "").upper() != XERO_ORGANISATION_TYPE:
        raise ValueError("Only organisation connections can be selected")

    previous_org = (integration.provider_tenant_id or "").strip()
    new_org = (row.xero_tenant_id or "").strip()

    await db.execute(
        update(XeroConnection)
        .where(
            XeroConnection.accounting_integration_id == integration.id,
            XeroConnection.tenant_id == tenant_id,
        )
        .values(selected=False)
    )
    row.selected = True
    integration.provider_tenant_id = row.xero_tenant_id
    integration.xero_connection_id = row.xero_connection_id
    integration.provider_tenant_type = row.xero_tenant_type
    integration.display_name = row.xero_tenant_name
    integration.status = AccountingIntegrationStatus.CONNECTED.value
    integration.last_error = None
    integration.last_error_code = None

    # Organisation switch: deactivate prior org master data + mappings.
    # Same-org reconnect leaves rows active so sync can update in place.
    if previous_org and new_org and previous_org != new_org:
        from app.integrations.xero.organisation_isolation import (
            deactivate_xero_organisation_scope,
        )

        await deactivate_xero_organisation_scope(
            db,
            tenant_id=tenant_id,
            xero_tenant_id=previous_org,
        )
        logger.info(
            "xero_organisation_switched",
            tenant_id=str(tenant_id),
            previous_xero_tenant_id=previous_org,
            xero_tenant_id=new_org,
        )

    await db.flush()
    return integration


async def disconnect_integration(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    provider: str,
) -> AccountingIntegration | None:
    if provider == AccountingProvider.XERO.value:
        return await disconnect_xero(db, tenant_id=tenant_id)
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


async def disconnect_xero(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> AccountingIntegration | None:
    row = await get_integration(db, tenant_id, AccountingProvider.XERO.value)
    if row is None:
        return None

    connections = await _list_xero_connection_rows(db, row.id)
    selected = next((c for c in connections if c.selected), None)
    target = selected or (connections[0] if len(connections) == 1 else None)
    if target and row.access_token_encrypted:
        try:
            access_token = decrypt_secret(row.access_token_encrypted)
            if access_token:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    await client.delete(
                        f"{get_settings().xero_connections_url}/{target.xero_connection_id}",
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Accept": "application/json",
                        },
                    )
        except Exception as exc:
            logger.warning(
                "xero_disconnect_remote_failed",
                tenant_id=str(tenant_id),
                error=str(exc),
            )

    now = datetime.now(timezone.utc)
    for connection in connections:
        connection.active = False
        connection.selected = False
        connection.disconnected_at = now

    row.status = AccountingIntegrationStatus.DISCONNECTED.value
    row.access_token_encrypted = None
    row.refresh_token_encrypted = None
    row.expires_at = None
    row.provider_tenant_id = None
    row.xero_connection_id = None
    row.provider_tenant_type = None
    row.display_name = None
    row.last_error = None
    row.last_error_code = None
    row.last_successful_sync_at = None
    row.token_version = 0
    row.last_refresh_at = None

    from app.integrations.xero.sync_jobs import cancel_pending_jobs

    await cancel_pending_jobs(db, tenant_id=tenant_id)
    await db.flush()
    return row


async def _upsert_xero_connections(
    db: AsyncSession,
    *,
    integration: AccountingIntegration,
    tenant_id: uuid.UUID,
    connections: list[dict[str, Any]],
) -> list[XeroConnection]:
    from app.integrations.xero.store import upsert_connections as persist_connections

    return await persist_connections(
        db,
        integration=integration,
        tenant_id=tenant_id,
        connections=connections,
    )


async def _apply_xero_org_selection(
    db: AsyncSession,
    *,
    integration: AccountingIntegration,
    connections: list[XeroConnection],
) -> AccountingIntegration:
    organisations = [
        c
        for c in connections
        if c.active and (c.xero_tenant_type or "").upper() == XERO_ORGANISATION_TYPE
    ]
    previous_org = (integration.provider_tenant_id or "").strip()
    await db.execute(
        update(XeroConnection)
        .where(XeroConnection.accounting_integration_id == integration.id)
        .values(selected=False)
    )
    if len(organisations) == 1:
        org = organisations[0]
        org.selected = True
        new_org = (org.xero_tenant_id or "").strip()
        integration.provider_tenant_id = org.xero_tenant_id
        integration.xero_connection_id = org.xero_connection_id
        integration.provider_tenant_type = org.xero_tenant_type
        integration.display_name = org.xero_tenant_name
        integration.status = AccountingIntegrationStatus.CONNECTED.value
        if previous_org and new_org and previous_org != new_org:
            from app.integrations.xero.organisation_isolation import (
                deactivate_xero_organisation_scope,
            )

            await deactivate_xero_organisation_scope(
                db,
                tenant_id=integration.tenant_id,
                xero_tenant_id=previous_org,
            )
    elif len(organisations) > 1:
        if previous_org:
            from app.integrations.xero.organisation_isolation import (
                deactivate_xero_organisation_scope,
            )

            # Selection cleared pending user choice — do not leave prior org active.
            await deactivate_xero_organisation_scope(
                db,
                tenant_id=integration.tenant_id,
                xero_tenant_id=previous_org,
            )
        integration.provider_tenant_id = None
        integration.xero_connection_id = None
        integration.provider_tenant_type = None
        integration.display_name = None
        integration.status = AccountingIntegrationStatus.ORGANISATION_SELECTION_REQUIRED.value
    else:
        raise RuntimeError("No Xero organisations available for this account")
    await db.flush()
    return integration


async def _upsert_integration(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    provider: str,
    user_id: int,
    provider_tenant_id: str | None,
    display_name: str | None,
    access_token: str,
    refresh_token: str | None,
    expires_at: datetime | None,
    scopes: str | None,
    xero_connection_id: str | None = None,
    provider_tenant_type: str | None = None,
    status: str | None = None,
) -> AccountingIntegration:
    row = await get_integration(db, tenant_id, provider)
    now = datetime.now(timezone.utc)
    if row is None:
        row = AccountingIntegration(
            tenant_id=tenant_id,
            provider=provider,
        )
        db.add(row)
    row.status = status or AccountingIntegrationStatus.CONNECTED.value
    row.provider_tenant_id = provider_tenant_id
    row.xero_connection_id = xero_connection_id
    row.provider_tenant_type = provider_tenant_type
    row.display_name = display_name
    row.access_token_encrypted = encrypt_secret(access_token)
    row.refresh_token_encrypted = encrypt_secret(refresh_token) if refresh_token else None
    row.expires_at = expires_at
    row.scopes = scopes
    row.connected_by_user_id = user_id
    row.connected_at = now
    row.last_error = None
    row.last_error_code = None
    row.token_version = int(row.token_version or 0)
    await db.flush()
    return row


async def disconnect_peer_accounting_provider(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    keep_provider: str,
) -> None:
    """Only one of Xero or QuickBooks may stay connected for a tenant."""
    if keep_provider == AccountingProvider.QUICKBOOKS_ONLINE.value:
        await disconnect_xero(db, tenant_id=tenant_id)
        return
    if keep_provider == AccountingProvider.XERO.value:
        await disconnect_integration(
            db,
            tenant_id=tenant_id,
            provider=AccountingProvider.QUICKBOOKS_ONLINE.value,
        )


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
    # STAGE 2: original token exchange commented — use app.integrations.xero.connect_api
    from app.integrations.xero.connect_api import complete_oauth_callback as new_complete

    return await new_complete(db, tenant_id=tenant_id, user_id=user_id, code=code)


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

    row = await _upsert_integration(
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
    await disconnect_peer_accounting_provider(
        db,
        tenant_id=tenant_id,
        keep_provider=AccountingProvider.QUICKBOOKS_ONLINE.value,
    )
    return row


async def sync_qbo_masters_after_connect(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Pull contacts, tax, accounts, and currencies. Safe to call after OAuth redirect."""
    try:
        from app.integrations.qbo.contacts import sync_contacts as sync_qbo_contacts

        async with db.begin_nested():
            await sync_qbo_contacts(db, tenant_id)
    except Exception as exc:
        logger.warning(
            "qbo_contacts_initial_sync_failed",
            tenant_id=str(tenant_id),
            error=str(exc),
        )
    try:
        from app.integrations.qbo.tax_codes import sync_tax_codes_from_qbo

        async with db.begin_nested():
            await sync_tax_codes_from_qbo(db, tenant_id)
    except Exception as exc:
        logger.warning(
            "qbo_tax_codes_initial_sync_failed",
            tenant_id=str(tenant_id),
            error=str(exc),
        )
    try:
        from app.integrations.qbo.accounts import sync_accounts_from_qbo

        async with db.begin_nested():
            await sync_accounts_from_qbo(db, tenant_id)
    except Exception as exc:
        logger.warning(
            "qbo_accounts_initial_sync_failed",
            tenant_id=str(tenant_id),
            error=str(exc),
        )
    try:
        from app.integrations.qbo.currencies import sync_currencies_from_qbo

        async with db.begin_nested():
            await sync_currencies_from_qbo(db, tenant_id)
    except Exception as exc:
        logger.warning(
            "qbo_currencies_initial_sync_failed",
            tenant_id=str(tenant_id),
            error=str(exc),
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
