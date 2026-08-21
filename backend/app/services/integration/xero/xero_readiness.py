"""Extended Xero readiness payload for API responses."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.accounting_integration import AccountingIntegrationStatus
from app.services.integration.accounting_integration_service import get_xero_readiness


def enrich_xero_readiness(payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    status = str(payload.get("status") or AccountingIntegrationStatus.DISCONNECTED.value)
    configured = bool(payload.get("configured"))
    display_name = payload.get("display_name")
    provider_tenant_id = payload.get("provider_tenant_id")
    return {
        "enabled": settings.xero_configured,
        "configured": configured,
        "connected": bool(payload.get("connected")),
        "ready": bool(payload.get("ready")),
        "status": status,
        "organisation_selection_required": status
        == AccountingIntegrationStatus.ORGANISATION_SELECTION_REQUIRED.value,
        "organisation_selected": bool(payload.get("organisation_selected")),
        "selected_xero_tenant_id": provider_tenant_id,
        "selected_xero_tenant_name": display_name,
        "provider_tenant_id": provider_tenant_id,
        "display_name": display_name,
        "connection_count": int(payload.get("connection_count") or 0),
        "scopes": payload.get("scopes"),
        "token_expires_at": payload.get("token_expires_at"),
        "needs_reauth": status == AccountingIntegrationStatus.NEEDS_REAUTH.value,
        "last_successful_sync_at": payload.get("last_successful_sync_at"),
        "last_error_code": payload.get("last_error_code"),
        "last_error_message": payload.get("last_error_message") or payload.get("last_error"),
        "last_error": payload.get("last_error"),
        "connection_verified": bool(payload.get("connection_verified")),
        "verified_at": payload.get("verified_at"),
    }


async def get_xero_readiness_enriched(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> dict[str, Any]:
    from app.models.accounting_integration import AccountingProvider
    from app.services.integration.accounting_integration_service import get_integration
    from app.services.integration.xero.xero_sync_job_service import get_latest_sync_job

    payload = await get_xero_readiness(db, tenant_id)
    integration = await get_integration(db, tenant_id, AccountingProvider.XERO.value)
    if integration is not None:
        payload = {
            **payload,
            "scopes": integration.scopes,
            "token_expires_at": integration.expires_at,
            "last_successful_sync_at": integration.last_successful_sync_at,
            "last_error_code": integration.last_error_code,
            "last_error_message": integration.last_error,
        }
    latest_job = await get_latest_sync_job(db, tenant_id=tenant_id)
    if latest_job is not None:
        payload["latest_sync_job_status"] = latest_job.status
        payload["latest_sync_job_type"] = latest_job.job_type
    return enrich_xero_readiness(payload)
