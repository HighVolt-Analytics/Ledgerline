"""Manual sync of Xero organisation settings and contacts into external refs."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting_integration import AccountingProvider
from app.models.external_accounting_ref import ExternalAccountingRef
from app.models.accounting_sync_job import JOB_TYPE_CONTACTS, JOB_TYPE_SETTINGS
from app.services.integration.accounting_integration_service import require_xero_ready
from app.services.integration.xero_client import XeroApiError, XeroClient
from app.services.integration.xero_sync_job_service import (
    enqueue_sync_job,
    mark_job_completed,
    mark_job_failed,
    mark_job_running,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_PROVIDER = AccountingProvider.XERO.value
_CONTACT_PAGE_SIZE = 100


def _normalize_contact_key(name: str) -> str:
    collapsed = re.sub(r"\s+", " ", (name or "").strip().lower())
    return collapsed[:255] or "unknown"


async def _upsert_ref(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    entity_type: str,
    internal_entity_id: str,
    external_entity_id: str,
    external_number: str | None = None,
    external_status: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExternalAccountingRef:
    row = (
        await db.execute(
            select(ExternalAccountingRef).where(
                ExternalAccountingRef.tenant_id == tenant_id,
                ExternalAccountingRef.provider == _PROVIDER,
                ExternalAccountingRef.entity_type == entity_type,
                ExternalAccountingRef.internal_entity_id == internal_entity_id,
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        row = ExternalAccountingRef(
            tenant_id=tenant_id,
            provider=_PROVIDER,
            entity_type=entity_type,
            internal_entity_id=internal_entity_id,
            external_entity_id=external_entity_id,
        )
        db.add(row)
    row.external_entity_id = external_entity_id
    row.external_number = external_number
    row.external_status = external_status
    row.last_synced_at = now
    row.last_error_code = None
    row.last_error_message = None
    row.sync_status = "synced"
    row.sync_attempts = int(row.sync_attempts or 0) + 1
    row.sync_error_code = None
    row.sync_error_message = None
    if metadata is not None:
        row.metadata_json = json.dumps(metadata)
    await db.flush()
    return row


async def _run_settings_sync(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, int]:
    integration, xero_tenant_id = await require_xero_ready(db, tenant_id)
    client = XeroClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)
    counts = {"organisation": 0, "account": 0, "tax_rate": 0, "currency": 0}

    org_payload = await client.get_json("Organisation")
    organisations = org_payload.get("Organisations") or []
    for org in organisations:
        org_id = str(org.get("OrganisationID") or xero_tenant_id)
        await _upsert_ref(
            db,
            tenant_id=tenant_id,
            entity_type="organisation",
            internal_entity_id=org_id,
            external_entity_id=org_id,
            external_number=org.get("ShortCode"),
            metadata=org,
        )
        counts["organisation"] += 1
        for currency in org.get("Currencies") or []:
            code = str(currency.get("Code") or "").strip()
            if not code:
                continue
            await _upsert_ref(
                db,
                tenant_id=tenant_id,
                entity_type="currency",
                internal_entity_id=code,
                external_entity_id=code,
                metadata=currency,
            )
            counts["currency"] += 1

    accounts_payload = await client.get_json("Accounts")
    for account in accounts_payload.get("Accounts") or []:
        account_id = str(account.get("AccountID") or "")
        code = str(account.get("Code") or account_id)
        if not account_id:
            continue
        await _upsert_ref(
            db,
            tenant_id=tenant_id,
            entity_type="account",
            internal_entity_id=code,
            external_entity_id=account_id,
            external_number=code,
            external_status=account.get("Status"),
            metadata=account,
        )
        counts["account"] += 1

    tax_payload = await client.get_json("TaxRates")
    for tax in tax_payload.get("TaxRates") or []:
        tax_type = str(tax.get("TaxType") or "")
        name = str(tax.get("Name") or tax_type)
        if not tax_type:
            continue
        await _upsert_ref(
            db,
            tenant_id=tenant_id,
            entity_type="tax_rate",
            internal_entity_id=tax_type,
            external_entity_id=tax_type,
            external_number=name,
            metadata=tax,
        )
        counts["tax_rate"] += 1

    integration.last_successful_sync_at = datetime.now(timezone.utc)
    await db.flush()
    return counts


async def _run_contacts_sync(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, int]:
    integration, xero_tenant_id = await require_xero_ready(db, tenant_id)
    client = XeroClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)
    synced = 0
    page = 1
    while True:
        payload = await client.get_json(
            "Contacts",
            params={"page": page, "pageSize": _CONTACT_PAGE_SIZE},
        )
        contacts = payload.get("Contacts") or []
        if not contacts:
            break
        for contact in contacts:
            contact_id = str(contact.get("ContactID") or "")
            name = str(contact.get("Name") or contact_id)
            if not contact_id:
                continue
            await _upsert_ref(
                db,
                tenant_id=tenant_id,
                entity_type="contact",
                internal_entity_id=_normalize_contact_key(name),
                external_entity_id=contact_id,
                external_number=contact.get("ContactNumber"),
                external_status=contact.get("ContactStatus"),
                metadata={"name": name, "contact_id": contact_id},
            )
            synced += 1
        if len(contacts) < _CONTACT_PAGE_SIZE:
            break
        page += 1

    integration.last_successful_sync_at = datetime.now(timezone.utc)
    await db.flush()
    return {"contact": synced}


async def sync_settings(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, int]:
    job = await enqueue_sync_job(db, tenant_id=tenant_id, job_type=JOB_TYPE_SETTINGS)
    await mark_job_running(db, job)
    try:
        counts = await _run_settings_sync(db, tenant_id)
        await mark_job_completed(db, job)
        counts["job_id"] = job.id
        return counts
    except (RuntimeError, XeroApiError) as exc:
        code = getattr(exc, "error_code", None) or "sync_failed"
        message = str(exc)
        await mark_job_failed(db, job, error_code=str(code), error_message=message)
        raise


async def sync_contacts(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, int]:
    job = await enqueue_sync_job(db, tenant_id=tenant_id, job_type=JOB_TYPE_CONTACTS)
    await mark_job_running(db, job)
    try:
        counts = await _run_contacts_sync(db, tenant_id)
        await mark_job_completed(db, job)
        counts["job_id"] = job.id
        return counts
    except (RuntimeError, XeroApiError) as exc:
        code = getattr(exc, "error_code", None) or "sync_failed"
        message = str(exc)
        await mark_job_failed(db, job, error_code=str(code), error_message=message)
        raise
