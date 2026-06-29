"""Accounting integrations — Xero and QuickBooks Online OAuth."""

from __future__ import annotations

import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, get_db, require_admin
from app.config import get_settings
from app.models.accounting_integration import AccountingProvider
from app.models.user import User, UserRole
from app.schemas.accounting_integration import (
    AccountingConnectResponse,
    AccountingDisconnectResponse,
    AccountingIntegrationItem,
    AccountingIntegrationsStatusResponse,
)
from app.schemas.common import ApiEnvelope
from app.services.accounting_integration_service import (
    build_connect_url,
    complete_oauth_callback,
    disconnect_integration,
    integration_status_item,
    list_integrations,
    parse_oauth_state,
    provider_label,
    quickbooks_configured,
    record_integration_error,
    xero_configured,
)
from app.services.audit_service import log_event
from app.tenant_ids import parse_tenant_id
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/integrations", tags=["accounting-integrations"])
oauth_public_router = APIRouter(prefix="/integrations", tags=["accounting-integrations-public"])

_OAUTH_ERRORS = {
    "not_configured": "Accounting integration credentials are not configured on the server.",
    "invalid_state": "OAuth session expired. Try connecting again.",
    "not_admin": "Only tenant admins can connect accounting integrations.",
    "oauth_failed": "OAuth connection failed. Try again.",
    "missing_code": "Authorization code missing from provider callback.",
    "missing_realm": "QuickBooks company (realm) id missing from callback.",
}


def _append_query(url: str, params: dict[str, str]) -> str:
    if not params:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"


def _frontend_return_url() -> str:
    return get_settings().accounting_oauth_frontend_return_url_resolved


def _callback_query_key(provider: str) -> str:
    if provider == AccountingProvider.XERO.value:
        return "xero"
    return "quickbooks"


async def _require_admin_user(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: int,
) -> User:
    user = await db.get(User, user_id)
    if not user or not user.is_active or user.tenant_id != tenant_id:
        raise HTTPException(403, _OAUTH_ERRORS["not_admin"])
    if user.role != UserRole.ADMIN:
        raise HTTPException(403, _OAUTH_ERRORS["not_admin"])
    return user


def _status_response(rows: list) -> AccountingIntegrationsStatusResponse:
    by_provider = {row.provider: row for row in rows}
    return AccountingIntegrationsStatusResponse(
        xero=AccountingIntegrationItem.model_validate(
            integration_status_item(
                AccountingProvider.XERO.value,
                by_provider.get(AccountingProvider.XERO.value),
            )
        ),
        quickbooks_online=AccountingIntegrationItem.model_validate(
            integration_status_item(
                AccountingProvider.QUICKBOOKS_ONLINE.value,
                by_provider.get(AccountingProvider.QUICKBOOKS_ONLINE.value),
            )
        ),
    )


@router.get("/status", response_model=ApiEnvelope[AccountingIntegrationsStatusResponse])
async def accounting_integrations_status(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[AccountingIntegrationsStatusResponse]:
    rows = await list_integrations(db, ctx.tenant_id)
    return ApiEnvelope(data=_status_response(rows))


@router.get("/xero/connect", response_model=ApiEnvelope[AccountingConnectResponse])
async def xero_connect(
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[AccountingConnectResponse]:
    if not xero_configured():
        raise HTTPException(503, _OAUTH_ERRORS["not_configured"])
    url = build_connect_url(
        provider=AccountingProvider.XERO.value,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id or 0,
    )
    return ApiEnvelope(data=AccountingConnectResponse(connect_url=url))


@router.get("/quickbooks/connect", response_model=ApiEnvelope[AccountingConnectResponse])
async def quickbooks_connect(
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[AccountingConnectResponse]:
    if not quickbooks_configured():
        raise HTTPException(503, _OAUTH_ERRORS["not_configured"])
    url = build_connect_url(
        provider=AccountingProvider.QUICKBOOKS_ONLINE.value,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id or 0,
    )
    return ApiEnvelope(data=AccountingConnectResponse(connect_url=url))


@router.post(
    "/{provider}/disconnect",
    response_model=ApiEnvelope[AccountingDisconnectResponse],
)
async def accounting_disconnect(
    provider: str,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[AccountingDisconnectResponse]:
    if provider not in (
        AccountingProvider.XERO.value,
        AccountingProvider.QUICKBOOKS_ONLINE.value,
    ):
        raise HTTPException(404, "Unknown accounting provider")

    row = await disconnect_integration(db, tenant_id=ctx.tenant_id, provider=provider)
    if row is None:
        return ApiEnvelope(
            data=AccountingDisconnectResponse(disconnected=True, provider=provider),
        )

    actor_name, actor_email = await actor_from_context(db, ctx)
    await log_event(
        db,
        "accounting_integration_disconnected",
        tenant_id=ctx.tenant_id,
        detail={
            "provider": provider,
            "provider_label": provider_label(provider),
            "display_name": row.display_name,
            "provider_tenant_id": row.provider_tenant_id,
        },
        actor_name=actor_name,
        actor_email=actor_email,
    )
    return ApiEnvelope(
        data=AccountingDisconnectResponse(disconnected=True, provider=provider),
    )


@oauth_public_router.get("/xero/callback")
async def xero_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    provider = AccountingProvider.XERO.value
    return_base = _frontend_return_url()
    query_key = _callback_query_key(provider)

    if error:
        message = (error_description or error)[:120]
        url = _append_query(return_base, {query_key: "error", "reason": message})
        return RedirectResponse(url=url, status_code=302)

    if not code or not state:
        url = _append_query(return_base, {query_key: "error", "reason": "missing_code"})
        return RedirectResponse(url=url, status_code=302)

    try:
        payload = parse_oauth_state(state, provider=provider)
        tenant_id = parse_tenant_id(payload["org_id"])
        if tenant_id is None:
            raise ValueError("Invalid OAuth session")
        user_id = int(payload["sub"])
    except Exception as exc:
        logger.warning("xero_oauth_state_invalid", error=str(exc))
        url = _append_query(return_base, {query_key: "error", "reason": "invalid_state"})
        return RedirectResponse(url=url, status_code=302)

    try:
        await _require_admin_user(db, tenant_id=tenant_id, user_id=user_id)
    except HTTPException:
        url = _append_query(return_base, {query_key: "error", "reason": "not_admin"})
        return RedirectResponse(url=url, status_code=302)

    try:
        row = await complete_oauth_callback(
            db,
            provider=provider,
            code=code,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        user = await db.get(User, user_id)
        await log_event(
            db,
            "accounting_integration_connected",
            tenant_id=tenant_id,
            detail={
                "provider": provider,
                "provider_label": provider_label(provider),
                "display_name": row.display_name,
                "provider_tenant_id": row.provider_tenant_id,
            },
            actor_name=user.full_name if user else None,
            actor_email=user.email if user else None,
        )
        await db.commit()
        company = (row.display_name or "Xero")[:80]
        url = _append_query(return_base, {query_key: "connected", "company": company})
        return RedirectResponse(url=url, status_code=302)
    except Exception as exc:
        logger.warning("xero_oauth_callback_failed", error=str(exc), tenant_id=str(tenant_id))
        await record_integration_error(
            db,
            tenant_id=tenant_id,
            provider=provider,
            message=str(exc),
        )
        await log_event(
            db,
            "accounting_integration_error",
            tenant_id=tenant_id,
            detail={
                "provider": provider,
                "reason": str(exc)[:200],
            },
        )
        await db.commit()
        url = _append_query(return_base, {query_key: "error", "reason": "oauth_failed"})
        return RedirectResponse(url=url, status_code=302)


@oauth_public_router.get("/quickbooks/callback")
async def quickbooks_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    realmId: str | None = Query(None, alias="realmId"),
    error: str | None = None,
    error_description: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    provider = AccountingProvider.QUICKBOOKS_ONLINE.value
    return_base = _frontend_return_url()
    query_key = _callback_query_key(provider)

    if error:
        message = (error_description or error)[:120]
        url = _append_query(return_base, {query_key: "error", "reason": message})
        return RedirectResponse(url=url, status_code=302)

    if not code or not state:
        url = _append_query(return_base, {query_key: "error", "reason": "missing_code"})
        return RedirectResponse(url=url, status_code=302)

    if not realmId:
        url = _append_query(return_base, {query_key: "error", "reason": "missing_realm"})
        return RedirectResponse(url=url, status_code=302)

    try:
        payload = parse_oauth_state(state, provider=provider)
        tenant_id = parse_tenant_id(payload["org_id"])
        if tenant_id is None:
            raise ValueError("Invalid OAuth session")
        user_id = int(payload["sub"])
    except Exception as exc:
        logger.warning("quickbooks_oauth_state_invalid", error=str(exc))
        url = _append_query(return_base, {query_key: "error", "reason": "invalid_state"})
        return RedirectResponse(url=url, status_code=302)

    try:
        await _require_admin_user(db, tenant_id=tenant_id, user_id=user_id)
    except HTTPException:
        url = _append_query(return_base, {query_key: "error", "reason": "not_admin"})
        return RedirectResponse(url=url, status_code=302)

    try:
        row = await complete_oauth_callback(
            db,
            provider=provider,
            code=code,
            tenant_id=tenant_id,
            user_id=user_id,
            realm_id=realmId,
        )
        user = await db.get(User, user_id)
        await log_event(
            db,
            "accounting_integration_connected",
            tenant_id=tenant_id,
            detail={
                "provider": provider,
                "provider_label": provider_label(provider),
                "display_name": row.display_name,
                "provider_tenant_id": row.provider_tenant_id,
            },
            actor_name=user.full_name if user else None,
            actor_email=user.email if user else None,
        )
        await db.commit()
        company = (row.display_name or "QuickBooks")[:80]
        url = _append_query(return_base, {query_key: "connected", "company": company})
        return RedirectResponse(url=url, status_code=302)
    except Exception as exc:
        logger.warning(
            "quickbooks_oauth_callback_failed",
            error=str(exc),
            tenant_id=str(tenant_id),
        )
        await record_integration_error(
            db,
            tenant_id=tenant_id,
            provider=provider,
            message=str(exc),
        )
        await log_event(
            db,
            "accounting_integration_error",
            tenant_id=tenant_id,
            detail={
                "provider": provider,
                "reason": str(exc)[:200],
            },
        )
        await db.commit()
        url = _append_query(return_base, {query_key: "error", "reason": "oauth_failed"})
        return RedirectResponse(url=url, status_code=302)
