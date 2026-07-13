"""Accounting integrations — Xero and QuickBooks Online OAuth."""

from __future__ import annotations

import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, actor_from_context, bind_db_to_tenant, get_db, require_admin
from app.config import get_settings
from app.models.accounting_integration import AccountingIntegrationStatus, AccountingProvider
from app.models.user import User, UserRole
from app.schemas.accounting_integration import (
    AccountingConnectResponse,
    AccountingDisconnectResponse,
    AccountingIntegrationItem,
    AccountingIntegrationsStatusResponse,
    XeroConnectionsResponse,
    XeroConnectionItem,
    XeroInvoiceStatusResponse,
    XeroPushInvoiceResponse,
    XeroReadinessResponse,
    XeroSelectConnectionRequest,
    XeroSelectConnectionResponse,
    XeroSyncContactsResponse,
    XeroSyncSettingsResponse,
)
from app.schemas.common import ApiEnvelope
from app.services.integration.accounting_integration_service import (
    build_connect_url,
    complete_oauth_callback,
    disconnect_integration,
    
    integration_status_item,
    list_integrations,
    list_xero_connections,
    parse_oauth_state,
    provider_label,
    quickbooks_configured,
    record_integration_error,
    select_xero_connection,
    validate_oauth_state_replay,
    xero_configured,
)
from app.services.integration.xero_client import XeroApiError
from app.services.integration.xero_push_service import get_invoice_xero_status, push_invoice_to_xero
from app.services.integration.xero_readiness import get_xero_readiness_enriched
from app.services.integration.xero_sync_service import (
    mark_sync_committed,
    sync_contacts,
    sync_settings,
)
from app.services.audit.audit_service import log_event
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


@router.get("/xero/readiness", response_model=ApiEnvelope[XeroReadinessResponse])
async def xero_readiness(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[XeroReadinessResponse]:
    data = await get_xero_readiness_enriched(db, ctx.tenant_id)
    return ApiEnvelope(data=XeroReadinessResponse.model_validate(data))


@router.get("/xero/connections", response_model=ApiEnvelope[XeroConnectionsResponse])
async def xero_connections(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[XeroConnectionsResponse]:
    rows = await list_xero_connections(db, ctx.tenant_id)
    return ApiEnvelope(
        data=XeroConnectionsResponse(
            connections=[XeroConnectionItem.model_validate(row) for row in rows]
        )
    )


@router.post("/xero/connections/select", response_model=ApiEnvelope[XeroSelectConnectionResponse])
async def xero_select_connection(
    body: XeroSelectConnectionRequest,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[XeroSelectConnectionResponse]:
    try:
        row = await select_xero_connection(
            db,
            tenant_id=ctx.tenant_id,
            xero_connection_id=body.xero_connection_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    return ApiEnvelope(
        data=XeroSelectConnectionResponse(
            status=row.status,
            display_name=row.display_name,
            provider_tenant_id=row.provider_tenant_id,
        )
    )


@router.post("/xero/sync/settings", response_model=ApiEnvelope[XeroSyncSettingsResponse])
async def xero_sync_settings_route(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[XeroSyncSettingsResponse]:
    try:
        counts = await sync_settings(db, ctx.tenant_id)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except XeroApiError as exc:
        raise HTTPException(exc.status_code or 502, exc.message) from exc
    await db.commit()
    return ApiEnvelope(data=XeroSyncSettingsResponse.model_validate(mark_sync_committed(counts)))


@router.post("/xero/sync/contacts", response_model=ApiEnvelope[XeroSyncContactsResponse])
async def xero_sync_contacts_route(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[XeroSyncContactsResponse]:
    try:
        counts = await sync_contacts(db, ctx.tenant_id)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except XeroApiError as exc:
        raise HTTPException(exc.status_code or 502, exc.message) from exc
    await db.commit()
    return ApiEnvelope(data=XeroSyncContactsResponse.model_validate(mark_sync_committed(counts)))


@router.post(
    "/xero/invoices/{invoice_id}/push",
    response_model=ApiEnvelope[XeroPushInvoiceResponse],
)
async def xero_push_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[XeroPushInvoiceResponse]:
    try:
        result = await push_invoice_to_xero(
            db,
            tenant_id=ctx.tenant_id,
            invoice_id=invoice_id,
            user_id=ctx.user_id or 0,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except XeroApiError as exc:
        await db.commit()
        raise HTTPException(exc.status_code or 502, exc.message) from exc
    await db.commit()
    result["synced"] = True
    result["committed"] = True
    return ApiEnvelope(data=XeroPushInvoiceResponse.model_validate(result))


@router.get(
    "/xero/invoices/{invoice_id}/status",
    response_model=ApiEnvelope[XeroInvoiceStatusResponse],
)
async def xero_invoice_status(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[XeroInvoiceStatusResponse]:
    data = await get_invoice_xero_status(
        db,
        tenant_id=ctx.tenant_id,
        invoice_id=invoice_id,
    )
    return ApiEnvelope(data=XeroInvoiceStatusResponse.model_validate(data))


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
    await db.commit()
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
        await validate_oauth_state_replay(payload)
    except Exception as exc:
        logger.warning("xero_oauth_state_invalid", error=str(exc))
        url = _append_query(return_base, {query_key: "error", "reason": "invalid_state"})
        return RedirectResponse(url=url, status_code=302)

    try:
        await bind_db_to_tenant(db, tenant_id)
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
        redirect_params: dict[str, str]
        if row.status == AccountingIntegrationStatus.ORGANISATION_SELECTION_REQUIRED.value:
            redirect_params = {query_key: "organisation_selection_required"}
        else:
            company = (row.display_name or "Xero")[:80]
            redirect_params = {query_key: "connected", "company": company}
        url = _append_query(return_base, redirect_params)
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
        await validate_oauth_state_replay(payload)
    except Exception as exc:
        logger.warning("quickbooks_oauth_state_invalid", error=str(exc))
        url = _append_query(return_base, {query_key: "error", "reason": "invalid_state"})
        return RedirectResponse(url=url, status_code=302)

    try:
        await bind_db_to_tenant(db, tenant_id)
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

