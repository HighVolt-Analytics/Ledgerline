"""Verify Xero connection by calling Organisation API."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting_integration import (
    AccountingIntegrationStatus,
    AccountingProvider,
)
from app.models.xero_connection import XeroConnection
from app.services.integration.accounting_integration_service import (
    get_integration,
    get_xero_readiness,
)
from app.services.integration.xero.xero_client import XeroApiError, XeroClient
from app.services.integration.xero.xero_token_service import get_valid_access_token


async def verify_xero_connection(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> dict[str, Any]:
    readiness = await get_xero_readiness(db, tenant_id)
    integration = await get_integration(db, tenant_id, AccountingProvider.XERO.value)

    if integration is None or not integration.access_token_encrypted:
        return {
            "connected": False,
            "needs_reauth": False,
            "organisation_id": None,
            "organisation_name": None,
            "verified_at": None,
            "message": "Xero is not connected",
        }

    if integration.status == AccountingIntegrationStatus.NEEDS_REAUTH.value:
        return {
            "connected": False,
            "needs_reauth": True,
            "organisation_id": integration.provider_tenant_id,
            "organisation_name": integration.display_name,
            "verified_at": None,
            "message": integration.last_error or "Re-authentication required",
        }

    if not readiness.get("ready"):
        return {
            "connected": False,
            "needs_reauth": integration.status == AccountingIntegrationStatus.EXPIRED.value,
            "organisation_id": integration.provider_tenant_id,
            "organisation_name": integration.display_name,
            "verified_at": None,
            "message": "Select a Xero organisation before verifying",
        }

    xero_tenant_id = integration.provider_tenant_id or ""
    client = XeroClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)

    try:
        org_payload = await client.get_json("Organisation")
    except XeroApiError as exc:
        if exc.status_code == 401:
            try:
                await get_valid_access_token(db, tenant_id, force_refresh=True)
                org_payload = await client.get_json("Organisation")
            except RuntimeError:
                await db.refresh(integration)
                return {
                    "connected": False,
                    "needs_reauth": integration.status
                    == AccountingIntegrationStatus.NEEDS_REAUTH.value,
                    "organisation_id": integration.provider_tenant_id,
                    "organisation_name": integration.display_name,
                    "verified_at": None,
                    "message": integration.last_error or "Re-authentication required",
                }
        else:
            return {
                "connected": False,
                "needs_reauth": False,
                "organisation_id": integration.provider_tenant_id,
                "organisation_name": integration.display_name,
                "verified_at": None,
                "message": exc.message,
            }

    organisations = org_payload.get("Organisations") or []
    selected_org: dict[str, Any] | None = None
    for org in organisations:
        org_id = str(org.get("OrganisationID") or "")
        if org_id and org_id == xero_tenant_id:
            selected_org = org
            break
    if selected_org is None and organisations:
        selected_org = organisations[0]

    if selected_org is None:
        return {
            "connected": False,
            "needs_reauth": False,
            "organisation_id": xero_tenant_id or None,
            "organisation_name": integration.display_name,
            "verified_at": None,
            "message": "No organisation returned from Xero",
        }

    org_id = str(selected_org.get("OrganisationID") or xero_tenant_id)
    org_name = str(selected_org.get("Name") or integration.display_name or "")
    if org_id != xero_tenant_id:
        return {
            "connected": False,
            "needs_reauth": False,
            "organisation_id": org_id,
            "organisation_name": org_name,
            "verified_at": None,
            "message": "Selected tenant does not match Xero organisation",
        }

    verified_at = datetime.now(timezone.utc)
    connection_row = (
        await db.execute(
            select(XeroConnection).where(
                XeroConnection.tenant_id == tenant_id,
                XeroConnection.xero_tenant_id == xero_tenant_id,
                XeroConnection.selected.is_(True),
                XeroConnection.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if connection_row is not None:
        connection_row.last_verified_at = verified_at
        await db.flush()

    return {
        "connected": True,
        "needs_reauth": False,
        "organisation_id": org_id,
        "organisation_name": org_name,
        "verified_at": verified_at,
        "message": None,
    }
