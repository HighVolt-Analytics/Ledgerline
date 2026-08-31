"""List persisted Xero master-data rows for UI proof."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting_integration import AccountingIntegration, AccountingProvider
from app.models.accounting_sync_job import AccountingSyncJob
from app.models.external_accounting_ref import ExternalAccountingRef
from app.models.xero_account import XeroAccount
from app.models.xero_contact import XeroContact
from app.models.xero_currency import XeroCurrency
from app.models.xero_tax_rate import XeroTaxRate
from app.models.xero_webhook_event import XeroWebhookEvent


def _page_meta(*, total: int, limit: int, offset: int) -> dict[str, int]:
    return {"total": total, "limit": limit, "offset": offset}


async def resolve_selected_xero_tenant_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> str | None:
    row = (
        await db.execute(
            select(AccountingIntegration.provider_tenant_id).where(
                AccountingIntegration.tenant_id == tenant_id,
                AccountingIntegration.provider == AccountingProvider.XERO.value,
            )
        )
    ).scalar_one_or_none()
    value = (row or "").strip() if row else ""
    return value or None


async def list_xero_accounts(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    search: str | None = None,
    status: str | None = None,
    xero_tenant_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    org_id = xero_tenant_id
    if org_id is None:
        org_id = await resolve_selected_xero_tenant_id(db, tenant_id)
    stmt = select(XeroAccount).where(XeroAccount.tenant_id == tenant_id)
    count_stmt = select(func.count()).select_from(XeroAccount).where(
        XeroAccount.tenant_id == tenant_id
    )
    if org_id:
        stmt = stmt.where(XeroAccount.xero_tenant_id == org_id)
        count_stmt = count_stmt.where(XeroAccount.xero_tenant_id == org_id)
    else:
        # No selected organisation: never mix orgs in UI counts/lists.
        stmt = stmt.where(XeroAccount.xero_tenant_id == "")
        count_stmt = count_stmt.where(XeroAccount.xero_tenant_id == "")
    if status:
        stmt = stmt.where(XeroAccount.sync_status == status)
        count_stmt = count_stmt.where(XeroAccount.sync_status == status)
    if search:
        term = search.strip().lower()
        like = f"%{term}%"
        filt = or_(
            func.lower(XeroAccount.code).like(like),
            func.lower(XeroAccount.name).like(like),
        )
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(filt)
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    rows = (
        await db.execute(
            stmt.order_by(XeroAccount.code.asc().nulls_last(), XeroAccount.id.asc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return {
        "items": [_serialize_account(row) for row in rows],
        **_page_meta(total=total, limit=limit, offset=offset),
    }


async def list_xero_tax_rates(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    search: str | None = None,
    status: str | None = None,
    xero_tenant_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    org_id = xero_tenant_id
    if org_id is None:
        org_id = await resolve_selected_xero_tenant_id(db, tenant_id)
    stmt = select(XeroTaxRate).where(XeroTaxRate.tenant_id == tenant_id)
    count_stmt = select(func.count()).select_from(XeroTaxRate).where(
        XeroTaxRate.tenant_id == tenant_id
    )
    if org_id:
        stmt = stmt.where(XeroTaxRate.xero_tenant_id == org_id)
        count_stmt = count_stmt.where(XeroTaxRate.xero_tenant_id == org_id)
    else:
        stmt = stmt.where(XeroTaxRate.xero_tenant_id == "")
        count_stmt = count_stmt.where(XeroTaxRate.xero_tenant_id == "")
    if status:
        stmt = stmt.where(XeroTaxRate.sync_status == status)
        count_stmt = count_stmt.where(XeroTaxRate.sync_status == status)
    if search:
        term = search.strip().lower()
        like = f"%{term}%"
        filt = or_(
            func.lower(XeroTaxRate.tax_type).like(like),
            func.lower(XeroTaxRate.name).like(like),
        )
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(filt)
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    rows = (
        await db.execute(
            stmt.order_by(XeroTaxRate.tax_type.asc()).offset(offset).limit(limit)
        )
    ).scalars().all()
    return {
        "items": [_serialize_tax_rate(row) for row in rows],
        **_page_meta(total=total, limit=limit, offset=offset),
    }


async def list_xero_contacts(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    search: str | None = None,
    status: str | None = None,
    mapping_status: str | None = None,
    xero_tenant_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    org_id = xero_tenant_id
    if org_id is None:
        org_id = await resolve_selected_xero_tenant_id(db, tenant_id)
    stmt = select(XeroContact).where(XeroContact.tenant_id == tenant_id)
    count_stmt = select(func.count()).select_from(XeroContact).where(
        XeroContact.tenant_id == tenant_id
    )
    if org_id:
        stmt = stmt.where(XeroContact.xero_tenant_id == org_id)
        count_stmt = count_stmt.where(XeroContact.xero_tenant_id == org_id)
    else:
        stmt = stmt.where(XeroContact.xero_tenant_id == "")
        count_stmt = count_stmt.where(XeroContact.xero_tenant_id == "")
    if status:
        stmt = stmt.where(XeroContact.sync_status == status)
        count_stmt = count_stmt.where(XeroContact.sync_status == status)
    if mapping_status:
        stmt = stmt.where(XeroContact.mapping_status == mapping_status)
        count_stmt = count_stmt.where(XeroContact.mapping_status == mapping_status)
    if search:
        term = search.strip().lower()
        like = f"%{term}%"
        filt = or_(
            func.lower(XeroContact.name).like(like),
            func.lower(XeroContact.email_address).like(like),
            func.lower(XeroContact.xero_contact_id).like(like),
        )
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(filt)
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    rows = (
        await db.execute(
            stmt.order_by(XeroContact.name.asc().nulls_last(), XeroContact.id.asc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return {
        "items": [_serialize_contact(row) for row in rows],
        **_page_meta(total=total, limit=limit, offset=offset),
    }


async def get_master_data_totals(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    xero_tenant_id: str | None = None,
) -> dict[str, int]:
    org_id = xero_tenant_id
    if org_id is None:
        org_id = await resolve_selected_xero_tenant_id(db, tenant_id)
    if not org_id:
        return {
            "accounts": 0,
            "tax_rates": 0,
            "contacts": 0,
            "currencies": 0,
        }

    accounts = int(
        (
            await db.execute(
                select(func.count()).select_from(XeroAccount).where(
                    XeroAccount.tenant_id == tenant_id,
                    XeroAccount.xero_tenant_id == org_id,
                    XeroAccount.sync_status == "active",
                )
            )
        ).scalar_one()
        or 0
    )
    tax_rates = int(
        (
            await db.execute(
                select(func.count()).select_from(XeroTaxRate).where(
                    XeroTaxRate.tenant_id == tenant_id,
                    XeroTaxRate.xero_tenant_id == org_id,
                    XeroTaxRate.sync_status == "active",
                )
            )
        ).scalar_one()
        or 0
    )
    contacts = int(
        (
            await db.execute(
                select(func.count()).select_from(XeroContact).where(
                    XeroContact.tenant_id == tenant_id,
                    XeroContact.xero_tenant_id == org_id,
                    XeroContact.sync_status == "active",
                )
            )
        ).scalar_one()
        or 0
    )
    currencies = int(
        (
            await db.execute(
                select(func.count()).select_from(XeroCurrency).where(
                    XeroCurrency.tenant_id == tenant_id,
                    XeroCurrency.xero_tenant_id == org_id,
                    XeroCurrency.sync_status == "active",
                )
            )
        ).scalar_one()
        or 0
    )
    return {
        "accounts": accounts,
        "tax_rates": tax_rates,
        "contacts": contacts,
        "currencies": currencies,
    }



async def list_sync_history(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(AccountingSyncJob).where(
                    AccountingSyncJob.tenant_id == tenant_id,
                    AccountingSyncJob.provider == AccountingProvider.XERO.value,
                )
            )
        ).scalar_one()
        or 0
    )
    rows = (
        await db.execute(
            select(AccountingSyncJob)
            .where(
                AccountingSyncJob.tenant_id == tenant_id,
                AccountingSyncJob.provider == AccountingProvider.XERO.value,
            )
            .order_by(AccountingSyncJob.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return {
        "items": [_serialize_sync_job(row) for row in rows],
        **_page_meta(total=total, limit=limit, offset=offset),
    }



async def list_export_history(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    stmt = select(ExternalAccountingRef).where(
        ExternalAccountingRef.tenant_id == tenant_id,
        ExternalAccountingRef.provider == AccountingProvider.XERO.value,
        ExternalAccountingRef.entity_type == "invoice",
    )
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(ExternalAccountingRef).where(
                    ExternalAccountingRef.tenant_id == tenant_id,
                    ExternalAccountingRef.provider == AccountingProvider.XERO.value,
                    ExternalAccountingRef.entity_type == "invoice",
                )
            )
        ).scalar_one()
        or 0
    )
    rows = (
        await db.execute(
            stmt.order_by(ExternalAccountingRef.id.desc()).offset(offset).limit(limit)
        )
    ).scalars().all()
    return {
        "items": [_serialize_export_ref(row) for row in rows],
        **_page_meta(total=total, limit=limit, offset=offset),
    }


async def latest_webhook_at(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> datetime | None:
    return (
        await db.execute(
            select(func.max(XeroWebhookEvent.received_at)).where(
                XeroWebhookEvent.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()


def _provenance(**kwargs: Any) -> dict[str, Any]:
    return {
        "source_system": "xero",
        "source_label": "Source: Xero",
        **kwargs,
    }


def _serialize_account(row: XeroAccount) -> dict[str, Any]:
    return {
        "id": row.id,
        "xero_account_id": row.xero_account_id,
        "xero_tenant_id": row.xero_tenant_id,
        "code": row.code,
        "name": row.name,
        "account_type": row.account_type,
        "account_class": row.account_class,
        "status": row.status,
        "tax_type": row.tax_type,
        "currency_code": row.currency_code,
        "sync_status": row.sync_status,
        "last_synced_at": row.last_synced_at,
        "created_at": row.created_at,
        **_provenance(
            external_id=row.xero_account_id,
            imported_at=row.created_at,
        ),
    }


def _serialize_tax_rate(row: XeroTaxRate) -> dict[str, Any]:
    return {
        "id": row.id,
        "tax_type": row.tax_type,
        "xero_tenant_id": row.xero_tenant_id,
        "name": row.name,
        "status": row.status,
        "effective_rate": float(row.effective_rate) if row.effective_rate is not None else None,
        "display_tax_rate": float(row.display_tax_rate)
        if row.display_tax_rate is not None
        else None,
        "sync_status": row.sync_status,
        "last_synced_at": row.last_synced_at,
        "created_at": row.created_at,
        **_provenance(
            external_id=row.tax_type,
            imported_at=row.created_at,
        ),
    }


def _serialize_contact(row: XeroContact) -> dict[str, Any]:
    return {
        "id": row.id,
        "xero_contact_id": row.xero_contact_id,
        "xero_tenant_id": row.xero_tenant_id,
        "name": row.name,
        "email_address": row.email_address,
        "phone": row.phone,
        "contact_status": row.contact_status,
        "is_supplier": row.is_supplier,
        "is_customer": row.is_customer,
        "mapping_status": row.mapping_status,
        "mapped_vendor_id": row.mapped_vendor_id,
        "mapped_customer_id": row.mapped_customer_id,
        "sync_status": row.sync_status,
        "last_synced_at": row.last_synced_at,
        "created_at": row.created_at,
        **_provenance(
            external_id=row.xero_contact_id,
            imported_at=row.created_at,
        ),
    }


def _serialize_sync_job(row: AccountingSyncJob) -> dict[str, Any]:
    return {
        "id": row.id,
        "job_type": row.job_type,
        "direction": row.direction,
        "entity_type": row.entity_type,
        "status": row.status,
        "trigger_type": row.trigger_type,
        "records_fetched": row.records_fetched,
        "records_created": row.records_created,
        "records_updated": row.records_updated,
        "records_unchanged": row.records_unchanged,
        "records_failed": row.records_failed,
        "records_persisted": row.records_persisted,
        "attempts": row.attempts,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "correlation_id": row.correlation_id,
        "initiated_by": row.initiated_by,
        "created_at": row.created_at,
    }



def _serialize_export_ref(row: ExternalAccountingRef) -> dict[str, Any]:
    return {
        "id": row.id,
        "invoice_id": int(row.internal_entity_id) if row.internal_entity_id.isdigit() else None,
        "external_entity_id": row.external_entity_id,
        "external_number": row.external_number,
        "external_status": row.external_status,
        "sync_direction": row.sync_direction,
        "sync_status": row.sync_status,
        "reconciliation_status": row.reconciliation_status,
        "last_pushed_at": row.last_pushed_at,
        "last_synced_at": row.last_synced_at,
        "last_reconciled_at": row.last_reconciled_at,
        "last_remote_modified_at": row.last_remote_modified_at,
        "amount_due": float(row.amount_due) if row.amount_due is not None else None,
        "amount_paid": float(row.amount_paid) if row.amount_paid is not None else None,
        "is_fully_paid": row.is_fully_paid,
        "sync_error_code": row.sync_error_code,
        "sync_error_message": row.sync_error_message,
        "source_system": row.source_system or "ledgerlink",
    }
