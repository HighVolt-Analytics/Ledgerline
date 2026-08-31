"""Manual sync of Xero organisation settings and contacts into master tables."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting_integration import AccountingProvider
from app.models.accounting_sync_job import JOB_TYPE_CONTACTS, JOB_TYPE_SETTINGS
from app.models.xero_account import SOURCE_SYSTEM_XERO, XeroAccount
from app.models.xero_contact import MAPPING_UNMAPPED, XeroContact
from app.models.xero_currency import XeroCurrency
from app.models.xero_organisation_profile import XeroOrganisationProfile
from app.models.xero_tax_rate import XeroTaxRate
from app.models.xero_tracking_category import XeroTrackingCategory
from app.integrations.xero.client import XeroApiClient, XeroApiError
from app.integrations.xero.store import require_xero_ready
from app.integrations.xero.tax_rates import upsert_tax_rate_from_xero_payload
from app.integrations.xero.sync_counts import (
    ContactsSyncResult,
    SettingsSyncResult,
    payload_hash,
)
from app.services.integration.xero.xero_sync_job_service import (
    enqueue_sync_job,
    mark_job_completed,
    mark_job_failed,
    mark_job_running,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_PROVIDER = AccountingProvider.XERO.value
_CONTACT_PAGE_SIZE = 100
_SYNC_ACTIVE = "active"
_SYNC_INACTIVE = "inactive"


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _phone_from_contact(payload: dict[str, Any]) -> str | None:
    phones = payload.get("Phones") or []
    for phone in phones:
        number = str(phone.get("PhoneNumber") or "").strip()
        if number:
            return number[:64]
    return None


async def _run_settings_sync(db: AsyncSession, tenant_id: uuid.UUID) -> SettingsSyncResult:
    integration, xero_tenant_id = await require_xero_ready(db, tenant_id)
    client = XeroApiClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)
    result = SettingsSyncResult()
    now = datetime.now(timezone.utc)
    seen_account_ids: set[str] = set()
    seen_tax_types: set[str] = set()
    seen_currency_codes: set[str] = set()

    org_payload = await client.get_json("Organisation")
    organisations = org_payload.get("Organisations") or []
    for org in organisations:
        result.organisation.fetched += 1
        try:
            org_id = str(org.get("OrganisationID") or "").strip() or None
            hash_value = payload_hash(org)
            existing_org = (
                await db.execute(
                    select(XeroOrganisationProfile).where(
                        XeroOrganisationProfile.tenant_id == tenant_id,
                        XeroOrganisationProfile.xero_tenant_id == xero_tenant_id,
                    )
                )
            ).scalar_one_or_none()
            fields = {
                "organisation_id": org_id,
                "name": str(org.get("Name") or "")[:255] or None,
                "legal_name": str(org.get("LegalName") or "")[:255] or None,
                "base_currency": str(org.get("BaseCurrency") or "")[:8] or None,
                "country_code": str(org.get("CountryCode") or "")[:8] or None,
                "organisation_status": str(org.get("OrganisationStatus") or "")[:64] or None,
                "is_active": True,
                "payload_hash": hash_value,
                "raw_payload_json": json.dumps(org, default=str),
                "source_updated_at": _parse_dt(org.get("UpdatedDateUTC")),
                "last_synced_at": now,
            }
            if existing_org is None:
                db.add(
                    XeroOrganisationProfile(
                        tenant_id=tenant_id,
                        accounting_integration_id=integration.id,
                        xero_tenant_id=xero_tenant_id,
                        **fields,
                    )
                )
                result.organisation.created += 1
            elif existing_org.payload_hash == hash_value:
                existing_org.last_synced_at = now
                result.organisation.unchanged += 1
            else:
                for key, value in fields.items():
                    setattr(existing_org, key, value)
                result.organisation.updated += 1
        except Exception as exc:
            result.organisation.failed += 1
            logger.warning(
                "xero_organisation_upsert_failed",
                tenant_id=str(tenant_id),
                error=str(exc),
            )

    # Currencies live on GET Currencies — Organisation payloads typically omit them.
    currencies_remote = await client.get_currencies()
    for currency in currencies_remote:
        code = str(currency.get("Code") or "").strip().upper()
        if not code:
            continue
        result.currencies.fetched += 1
        try:
            seen_currency_codes.add(code)
            hash_value = payload_hash(currency)
            existing = (
                await db.execute(
                    select(XeroCurrency).where(
                        XeroCurrency.tenant_id == tenant_id,
                        XeroCurrency.xero_tenant_id == xero_tenant_id,
                        XeroCurrency.code == code,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                db.add(
                    XeroCurrency(
                        tenant_id=tenant_id,
                        accounting_integration_id=integration.id,
                        xero_tenant_id=xero_tenant_id,
                        code=code,
                        description=str(currency.get("Description") or "")[:255] or None,
                        source_system=SOURCE_SYSTEM_XERO,
                        sync_status=_SYNC_ACTIVE,
                        payload_hash=hash_value,
                        raw_payload_json=json.dumps(currency, default=str),
                        last_seen_at=now,
                        last_synced_at=now,
                    )
                )
                result.currencies.created += 1
            elif existing.payload_hash == hash_value and existing.sync_status == _SYNC_ACTIVE:
                existing.last_seen_at = now
                existing.last_synced_at = now
                result.currencies.unchanged += 1
            else:
                existing.description = str(currency.get("Description") or "")[:255] or None
                existing.sync_status = _SYNC_ACTIVE
                existing.payload_hash = hash_value
                existing.raw_payload_json = json.dumps(currency, default=str)
                existing.last_seen_at = now
                existing.last_synced_at = now
                result.currencies.updated += 1
        except Exception as exc:
            result.currencies.failed += 1
            logger.warning(
                "xero_currency_upsert_failed",
                tenant_id=str(tenant_id),
                code=code,
                error=str(exc),
            )

    accounts_payload = await client.get_json("Accounts")
    for account in accounts_payload.get("Accounts") or []:
        account_id = str(account.get("AccountID") or "").strip()
        if not account_id:
            continue
        result.accounts.fetched += 1
        try:
            seen_account_ids.add(account_id)
            hash_value = payload_hash(account)
            existing = (
                await db.execute(
                    select(XeroAccount).where(
                        XeroAccount.tenant_id == tenant_id,
                        XeroAccount.xero_tenant_id == xero_tenant_id,
                        XeroAccount.xero_account_id == account_id,
                    )
                )
            ).scalar_one_or_none()
            fields = {
                "code": str(account.get("Code") or "")[:64] or None,
                "name": str(account.get("Name") or "")[:255] or None,
                "account_type": str(account.get("Type") or "")[:64] or None,
                "account_class": str(account.get("Class") or "")[:64] or None,
                "status": str(account.get("Status") or "")[:32] or None,
                "tax_type": str(account.get("TaxType") or "")[:64] or None,
                "currency_code": str(account.get("CurrencyCode") or "")[:8] or None,
                "enable_payments_to_account": bool(account["EnablePaymentsToAccount"])
                if "EnablePaymentsToAccount" in account
                else None,
                "show_in_expense_claims": bool(account["ShowInExpenseClaims"])
                if "ShowInExpenseClaims" in account
                else None,
                "description": str(account.get("Description") or "")[:512] or None,
                "last_remote_modified_at": _parse_dt(account.get("UpdatedDateUTC")),
            }
            if existing is None:
                db.add(
                    XeroAccount(
                        tenant_id=tenant_id,
                        accounting_integration_id=integration.id,
                        xero_tenant_id=xero_tenant_id,
                        xero_account_id=account_id,
                        source_system=SOURCE_SYSTEM_XERO,
                        sync_status=_SYNC_ACTIVE,
                        payload_hash=hash_value,
                        raw_payload_json=json.dumps(account, default=str),
                        last_seen_at=now,
                        last_synced_at=now,
                        **fields,
                    )
                )
                result.accounts.created += 1
            elif existing.payload_hash == hash_value and existing.sync_status == _SYNC_ACTIVE:
                existing.last_seen_at = now
                existing.last_synced_at = now
                result.accounts.unchanged += 1
            else:
                for key, value in fields.items():
                    setattr(existing, key, value)
                existing.sync_status = _SYNC_ACTIVE
                existing.payload_hash = hash_value
                existing.raw_payload_json = json.dumps(account, default=str)
                existing.last_seen_at = now
                existing.last_synced_at = now
                result.accounts.updated += 1
        except Exception as exc:
            result.accounts.failed += 1
            logger.warning(
                "xero_account_upsert_failed",
                tenant_id=str(tenant_id),
                account_id=account_id,
                error=str(exc),
            )

    tax_payload = await client.get_json("TaxRates")
    for tax in tax_payload.get("TaxRates") or []:
        tax_type = str(tax.get("TaxType") or "").strip()
        if not tax_type:
            continue
        result.tax_rates.fetched += 1
        try:
            seen_tax_types.add(tax_type)
            outcome = await upsert_tax_rate_from_xero_payload(
                db,
                tenant_id=tenant_id,
                integration_id=integration.id,
                xero_tenant_id=xero_tenant_id,
                tax=tax,
                now=now,
            )
            if outcome == "created":
                result.tax_rates.created += 1
            elif outcome == "updated":
                result.tax_rates.updated += 1
            elif outcome == "unchanged":
                result.tax_rates.unchanged += 1
        except Exception as exc:
            result.tax_rates.failed += 1
            logger.warning(
                "xero_tax_rate_upsert_failed",
                tenant_id=str(tenant_id),
                tax_type=tax_type,
                error=str(exc),
            )

    # Tracking categories / options
    seen_tracking_keys: set[str] = set()
    try:
        tracking_payload = await client.get_json("TrackingCategories")
    except XeroApiError as exc:
        logger.warning(
            "xero_tracking_categories_fetch_failed",
            tenant_id=str(tenant_id),
            error=str(exc),
        )
        tracking_payload = {"TrackingCategories": []}
    for category in tracking_payload.get("TrackingCategories") or []:
        category_id = str(category.get("TrackingCategoryID") or "").strip()
        if not category_id:
            continue
        options = category.get("Options") or [None]
        for option in options:
            result.tracking_categories.fetched += 1
            try:
                option_id = ""
                option_name = None
                option_status = None
                if isinstance(option, dict):
                    option_id = str(option.get("TrackingOptionID") or "").strip()
                    option_name = str(option.get("Name") or "")[:255] or None
                    option_status = str(option.get("Status") or "")[:32] or None
                key = f"{category_id}:{option_id}"
                seen_tracking_keys.add(key)
                row_payload = {
                    "category": category,
                    "option": option if isinstance(option, dict) else None,
                }
                hash_value = payload_hash(row_payload)
                existing = (
                    await db.execute(
                        select(XeroTrackingCategory).where(
                            XeroTrackingCategory.tenant_id == tenant_id,
                            XeroTrackingCategory.xero_tenant_id == xero_tenant_id,
                            XeroTrackingCategory.xero_tracking_category_id == category_id,
                            XeroTrackingCategory.option_external_id == (option_id or ""),
                        )
                    )
                ).scalar_one_or_none()
                fields = {
                    "name": str(category.get("Name") or "")[:255] or None,
                    "status": str(category.get("Status") or "")[:32] or None,
                    "option_external_id": option_id or "",
                    "option_name": option_name,
                    "option_status": option_status,
                    "sync_status": _SYNC_ACTIVE,
                    "is_active": True,
                    "payload_hash": hash_value,
                    "raw_payload_json": json.dumps(row_payload, default=str),
                    "source_updated_at": _parse_dt(category.get("UpdatedDateUTC")),
                    "last_synced_at": now,
                }
                if existing is None:
                    db.add(
                        XeroTrackingCategory(
                            tenant_id=tenant_id,
                            accounting_integration_id=integration.id,
                            xero_tenant_id=xero_tenant_id,
                            xero_tracking_category_id=category_id,
                            source_system=SOURCE_SYSTEM_XERO,
                            **fields,
                        )
                    )
                    result.tracking_categories.created += 1
                elif existing.payload_hash == hash_value and existing.sync_status == _SYNC_ACTIVE:
                    existing.last_synced_at = now
                    result.tracking_categories.unchanged += 1
                else:
                    for key_name, value in fields.items():
                        setattr(existing, key_name, value)
                    result.tracking_categories.updated += 1
            except Exception as exc:
                result.tracking_categories.failed += 1
                logger.warning(
                    "xero_tracking_upsert_failed",
                    tenant_id=str(tenant_id),
                    category_id=category_id,
                    error=str(exc),
                )

    for row in (
        await db.execute(
            select(XeroTrackingCategory).where(
                XeroTrackingCategory.tenant_id == tenant_id,
                XeroTrackingCategory.xero_tenant_id == xero_tenant_id,
                XeroTrackingCategory.sync_status == _SYNC_ACTIVE,
            )
        )
    ).scalars():
        key = f"{row.xero_tracking_category_id}:{row.option_external_id or ''}"
        if key not in seen_tracking_keys:
            row.sync_status = _SYNC_INACTIVE
            row.is_active = False
            row.last_synced_at = now
            result.tracking_categories.deactivated += 1

    # Deactivate rows missing from this complete sync
    for row in (
        await db.execute(
            select(XeroAccount).where(
                XeroAccount.tenant_id == tenant_id,
                XeroAccount.xero_tenant_id == xero_tenant_id,
                XeroAccount.sync_status == _SYNC_ACTIVE,
            )
        )
    ).scalars():
        if row.xero_account_id not in seen_account_ids:
            row.sync_status = _SYNC_INACTIVE
            row.last_synced_at = now
            result.accounts.deactivated += 1

    for row in (
        await db.execute(
            select(XeroTaxRate).where(
                XeroTaxRate.tenant_id == tenant_id,
                XeroTaxRate.xero_tenant_id == xero_tenant_id,
                XeroTaxRate.sync_status == _SYNC_ACTIVE,
            )
        )
    ).scalars():
        if row.tax_type not in seen_tax_types:
            row.sync_status = _SYNC_INACTIVE
            row.last_synced_at = now
            result.tax_rates.deactivated += 1

    for row in (
        await db.execute(
            select(XeroCurrency).where(
                XeroCurrency.tenant_id == tenant_id,
                XeroCurrency.xero_tenant_id == xero_tenant_id,
                XeroCurrency.sync_status == _SYNC_ACTIVE,
            )
        )
    ).scalars():
        if row.code not in seen_currency_codes:
            row.sync_status = _SYNC_INACTIVE
            row.last_synced_at = now
            result.currencies.deactivated += 1

    integration.last_successful_sync_at = now
    await db.flush()
    return result


async def _run_contacts_sync(db: AsyncSession, tenant_id: uuid.UUID) -> ContactsSyncResult:
    integration, xero_tenant_id = await require_xero_ready(db, tenant_id)
    client = XeroApiClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)
    result = ContactsSyncResult()
    now = datetime.now(timezone.utc)
    seen_ids: set[str] = set()
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
            contact_id = str(contact.get("ContactID") or "").strip()
            if not contact_id:
                continue
            result.contacts.fetched += 1
            try:
                seen_ids.add(contact_id)
                hash_value = payload_hash(contact)
                existing = (
                    await db.execute(
                        select(XeroContact).where(
                            XeroContact.tenant_id == tenant_id,
                            XeroContact.xero_tenant_id == xero_tenant_id,
                            XeroContact.xero_contact_id == contact_id,
                        )
                    )
                ).scalar_one_or_none()
                fields = {
                    "name": str(contact.get("Name") or "")[:255] or None,
                    "first_name": str(contact.get("FirstName") or "")[:128] or None,
                    "last_name": str(contact.get("LastName") or "")[:128] or None,
                    "email_address": str(contact.get("EmailAddress") or "")[:255] or None,
                    "phone": _phone_from_contact(contact),
                    "contact_status": str(contact.get("ContactStatus") or "")[:32] or None,
                    "is_supplier": bool(contact.get("IsSupplier")),
                    "is_customer": bool(contact.get("IsCustomer")),
                    "tax_number": str(contact.get("TaxNumber") or "")[:64] or None,
                    "default_currency": str(contact.get("DefaultCurrency") or "")[:8] or None,
                    "accounts_payable_tax_type": str(contact.get("AccountsPayableTaxType") or "")[:64]
                    or None,
                    "accounts_receivable_tax_type": str(
                        contact.get("AccountsReceivableTaxType") or ""
                    )[:64]
                    or None,
                    "last_remote_modified_at": _parse_dt(contact.get("UpdatedDateUTC")),
                }
                if existing is None:
                    db.add(
                        XeroContact(
                            tenant_id=tenant_id,
                            accounting_integration_id=integration.id,
                            xero_tenant_id=xero_tenant_id,
                            xero_contact_id=contact_id,
                            mapping_status=MAPPING_UNMAPPED,
                            source_system=SOURCE_SYSTEM_XERO,
                            sync_status=_SYNC_ACTIVE,
                            payload_hash=hash_value,
                            raw_payload_json=json.dumps(contact, default=str),
                            last_seen_at=now,
                            last_synced_at=now,
                            **fields,
                        )
                    )
                    result.contacts.created += 1
                elif existing.payload_hash == hash_value and existing.sync_status == _SYNC_ACTIVE:
                    existing.last_seen_at = now
                    existing.last_synced_at = now
                    result.contacts.unchanged += 1
                else:
                    for key, value in fields.items():
                        setattr(existing, key, value)
                    existing.sync_status = _SYNC_ACTIVE
                    existing.payload_hash = hash_value
                    existing.raw_payload_json = json.dumps(contact, default=str)
                    existing.last_seen_at = now
                    existing.last_synced_at = now
                    result.contacts.updated += 1
            except Exception as exc:
                result.contacts.failed += 1
                logger.warning(
                    "xero_contact_upsert_failed",
                    tenant_id=str(tenant_id),
                    contact_id=contact_id,
                    error=str(exc),
                )
        if len(contacts) < _CONTACT_PAGE_SIZE:
            break
        page += 1

    for row in (
        await db.execute(
            select(XeroContact).where(
                XeroContact.tenant_id == tenant_id,
                XeroContact.xero_tenant_id == xero_tenant_id,
                XeroContact.sync_status == _SYNC_ACTIVE,
            )
        )
    ).scalars():
        if row.xero_contact_id not in seen_ids:
            row.sync_status = _SYNC_INACTIVE
            row.last_synced_at = now
            result.contacts.deactivated += 1

    integration.last_successful_sync_at = now
    await db.flush()
    return result


async def sync_settings(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    job = await enqueue_sync_job(
        db,
        tenant_id=tenant_id,
        job_type=JOB_TYPE_SETTINGS,
        direction="inbound",
        entity_type="settings",
        trigger_type="manual",
    )
    await mark_job_running(db, job)
    try:
        result = await _run_settings_sync(db, tenant_id)
        await _apply_settings_job_counts(job, result)
        await mark_job_completed(db, job)
        result.job_id = job.id
        # Caller must commit; mark intended commit flag after successful flush only
        result.committed = False
        return result.to_response()
    except (RuntimeError, XeroApiError) as exc:
        code = getattr(exc, "error_code", None) or "sync_failed"
        await mark_job_failed(db, job, error_code=str(code), error_message=str(exc))
        raise


async def sync_contacts(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    job = await enqueue_sync_job(
        db,
        tenant_id=tenant_id,
        job_type=JOB_TYPE_CONTACTS,
        direction="inbound",
        entity_type="contact",
        trigger_type="manual",
    )
    await mark_job_running(db, job)
    try:
        result = await _run_contacts_sync(db, tenant_id)
        await _apply_contacts_job_counts(job, result)
        await mark_job_completed(db, job)
        result.job_id = job.id
        result.committed = False
        return result.to_response()
    except (RuntimeError, XeroApiError) as exc:
        code = getattr(exc, "error_code", None) or "sync_failed"
        await mark_job_failed(db, job, error_code=str(code), error_message=str(exc))
        raise


async def _apply_settings_job_counts(job: Any, result: SettingsSyncResult) -> None:
    accounts = result.accounts.to_dict()
    tax_rates = result.tax_rates.to_dict()
    currencies = result.currencies.to_dict()
    tracking = result.tracking_categories.to_dict()
    job.direction = "inbound"
    job.entity_type = "settings"
    job.trigger_type = "manual"
    job.records_fetched = (
        accounts["fetched"]
        + tax_rates["fetched"]
        + currencies["fetched"]
        + tracking["fetched"]
    )
    job.records_created = (
        accounts["created"]
        + tax_rates["created"]
        + currencies["created"]
        + tracking["created"]
    )
    job.records_updated = (
        accounts["updated"]
        + tax_rates["updated"]
        + currencies["updated"]
        + tracking["updated"]
    )
    job.records_unchanged = (
        accounts["unchanged"]
        + tax_rates["unchanged"]
        + currencies["unchanged"]
        + tracking["unchanged"]
    )
    job.records_failed = (
        accounts["failed"]
        + tax_rates["failed"]
        + currencies["failed"]
        + tracking["failed"]
    )
    job.records_persisted = (
        accounts["persisted_total"]
        + tax_rates["persisted_total"]
        + currencies["persisted_total"]
        + tracking["persisted_total"]
    )


async def _apply_contacts_job_counts(job: Any, result: ContactsSyncResult) -> None:
    data = result.contacts.to_dict()
    job.direction = "inbound"
    job.entity_type = "contact"
    job.trigger_type = "manual"
    job.records_fetched = data["fetched"]
    job.records_created = data["created"]
    job.records_updated = data["updated"]
    job.records_unchanged = data["unchanged"]
    job.records_failed = data["failed"]
    job.records_persisted = data["persisted_total"]


def mark_sync_committed(response: dict[str, Any]) -> dict[str, Any]:
    """Call after successful DB commit so clients never see uncommitted success."""
    response = dict(response)
    response["committed"] = True
    return response
