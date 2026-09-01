"""Xero chart of accounts: cache sync, create, update, archive."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.xero.account_types import XERO_DEFAULT_TAX_TYPE, ledger_type_for_xero
from app.integrations.xero.client import XeroApiClient, XeroApiError
from app.integrations.xero.store import require_xero_ready
from app.integrations.xero.sync_counts import EntitySyncCounters, payload_hash
from app.models.xero_account import SOURCE_SYSTEM_XERO, XeroAccount
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SYNC_ACTIVE = "active"
_SYNC_INACTIVE = "inactive"
_XERO_CODE_MAX = 10
_XERO_NAME_MAX = 150


class XeroAccountWriteError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def is_system_xero_account(row: XeroAccount) -> bool:
    payload = _parse_payload(row.raw_payload_json)
    system = str(payload.get("SystemAccount") or "").strip()
    return bool(system)


def _code_ok(code: str) -> str:
    cleaned = code.strip()
    if not cleaned:
        raise XeroAccountWriteError("Account code is required")
    if len(cleaned) > _XERO_CODE_MAX:
        raise XeroAccountWriteError("Xero account codes are limited to 10 characters")
    return cleaned


def _name_ok(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise XeroAccountWriteError("Account name is required")
    return cleaned[:_XERO_NAME_MAX]


async def upsert_account_from_xero_payload(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    integration_id: int,
    xero_tenant_id: str,
    account: dict[str, Any],
) -> XeroAccount | None:
    account_id = str(account.get("AccountID") or "").strip()
    if not account_id:
        return None
    now = _now()
    hash_value = payload_hash(account)
    status = str(account.get("Status") or "ACTIVE")[:32]
    sync_status = _SYNC_ACTIVE if status.upper() == "ACTIVE" else _SYNC_INACTIVE
    fields = {
        "code": str(account.get("Code") or "")[:64] or None,
        "name": str(account.get("Name") or "")[:255] or None,
        "account_type": str(account.get("Type") or "")[:64] or None,
        "account_class": str(account.get("Class") or "")[:64] or None,
        "status": status or None,
        "tax_type": str(account.get("TaxType") or "")[:64] or None,
        "currency_code": str(account.get("CurrencyCode") or "")[:8] or None,
        "enable_payments_to_account": bool(account["EnablePaymentsToAccount"])
        if "EnablePaymentsToAccount" in account
        else None,
        "show_in_expense_claims": bool(account["ShowInExpenseClaims"])
        if "ShowInExpenseClaims" in account
        else None,
        "description": str(account.get("Description") or "")[:512] or None,
        "sync_status": sync_status,
        "payload_hash": hash_value,
        "raw_payload_json": json.dumps(account, default=str),
        "last_seen_at": now,
        "last_synced_at": now,
    }
    existing = (
        await db.execute(
            select(XeroAccount).where(
                XeroAccount.tenant_id == tenant_id,
                XeroAccount.xero_tenant_id == xero_tenant_id,
                XeroAccount.xero_account_id == account_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        row = XeroAccount(
            tenant_id=tenant_id,
            accounting_integration_id=integration_id,
            xero_tenant_id=xero_tenant_id,
            xero_account_id=account_id,
            source_system=SOURCE_SYSTEM_XERO,
            **fields,
        )
        db.add(row)
        await db.flush()
        return row
    for key, value in fields.items():
        setattr(existing, key, value)
    await db.flush()
    return existing


async def list_active_xero_accounts(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    xero_tenant_id: str,
) -> list[XeroAccount]:
    rows = (
        await db.execute(
            select(XeroAccount)
            .where(
                XeroAccount.tenant_id == tenant_id,
                XeroAccount.xero_tenant_id == xero_tenant_id,
                XeroAccount.sync_status == _SYNC_ACTIVE,
            )
            .order_by(XeroAccount.code.asc().nulls_last(), XeroAccount.name.asc())
        )
    ).scalars().all()
    return [row for row in rows if (row.status or "ACTIVE").upper() == "ACTIVE"]


async def get_xero_account(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    xero_tenant_id: str,
    xero_account_id: str,
) -> XeroAccount | None:
    return (
        await db.execute(
            select(XeroAccount).where(
                XeroAccount.tenant_id == tenant_id,
                XeroAccount.xero_tenant_id == xero_tenant_id,
                XeroAccount.xero_account_id == xero_account_id,
            )
        )
    ).scalar_one_or_none()


async def sync_accounts_from_xero(db: AsyncSession, tenant_id: uuid.UUID) -> EntitySyncCounters:
    integration, xero_tenant_id = await require_xero_ready(db, tenant_id)
    client = XeroApiClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)
    try:
        payload = await client.get_json("Accounts")
    except XeroApiError as exc:
        raise XeroAccountWriteError(
            exc.message or "Could not fetch accounts from Xero",
            status_code=exc.status_code or 502,
        ) from exc
    if not isinstance(payload, dict):
        raise XeroAccountWriteError("Xero returned an unexpected accounts payload", status_code=502)
    counters = EntitySyncCounters()
    seen: set[str] = set()
    for account in payload.get("Accounts") or []:
        if not isinstance(account, dict):
            continue
        account_id = str(account.get("AccountID") or "").strip()
        if not account_id:
            continue
        counters.fetched += 1
        seen.add(account_id)
        before = await get_xero_account(db, tenant_id, xero_tenant_id, account_id)
        old_hash = before.payload_hash if before is not None else None
        await upsert_account_from_xero_payload(
            db,
            tenant_id=tenant_id,
            integration_id=integration.id,
            xero_tenant_id=xero_tenant_id,
            account=account,
        )
        if before is None:
            counters.created += 1
        elif old_hash == payload_hash(account):
            counters.unchanged += 1
        else:
            counters.updated += 1
    now = _now()
    existing_rows = (
        await db.execute(
            select(XeroAccount).where(
                XeroAccount.tenant_id == tenant_id,
                XeroAccount.xero_tenant_id == xero_tenant_id,
                XeroAccount.sync_status == _SYNC_ACTIVE,
            )
        )
    ).scalars().all()
    for row in existing_rows:
        if row.xero_account_id not in seen:
            row.sync_status = _SYNC_INACTIVE
            row.last_synced_at = now
            counters.deactivated += 1
    await db.flush()
    return counters


def _first_account(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    return next(
        (row for row in (payload.get("Accounts") or []) if isinstance(row, dict)),
        None,
    )


async def _tax_type_for_create(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    xero_tenant_id: str,
) -> str | None:
    from app.models.xero_tax_rate import XeroTaxRate

    rows = (
        await db.execute(
            select(XeroTaxRate.tax_type).where(
                XeroTaxRate.tenant_id == tenant_id,
                XeroTaxRate.xero_tenant_id == xero_tenant_id,
                XeroTaxRate.sync_status == _SYNC_ACTIVE,
            )
        )
    ).scalars().all()
    known = {str(item).strip().upper(): str(item).strip() for item in rows if str(item).strip()}
    for candidate in (XERO_DEFAULT_TAX_TYPE, "NONE", "EXEMPTOUTPUT", "EXEMPTINPUT"):
        if candidate in known:
            return known[candidate]
    return None


async def create_account_in_xero(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    code: str,
    name: str,
    xero_type: str,
) -> XeroAccount:
    integration, xero_tenant_id = await require_xero_ready(db, tenant_id)
    xero_type = xero_type.strip().upper()
    if xero_type == "BANK":
        raise XeroAccountWriteError(
            "Xero bank accounts need a bank account number. Use Current Asset, or create the bank account in Xero."
        )
    client = XeroApiClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)
    body: dict[str, Any] = {
        "Code": _code_ok(code),
        "Name": _name_ok(name),
        "Type": xero_type,
    }
    tax_type = await _tax_type_for_create(
        db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id
    )
    if tax_type:
        body["TaxType"] = tax_type
    try:
        payload = await client.put_json("Accounts", json_body=body)
    except XeroApiError as exc:
        lowered = (exc.message or "").lower()
        if exc.status_code == 400 and (
            "unique" in lowered or "already" in lowered or "exists" in lowered
        ):
            existing_payload = await client.get_json(
                "Accounts",
                params={"where": f'Code=="{_code_ok(code)}"'},
            )
            created = _first_account(existing_payload)
            if created is None:
                raise XeroAccountWriteError(
                    exc.message or "Xero rejected the account",
                    status_code=exc.status_code or 400,
                ) from exc
            payload = {"Accounts": [created]}
        else:
            raise XeroAccountWriteError(
                exc.message or "Xero rejected the account",
                status_code=exc.status_code or 502,
            ) from exc
    created = _first_account(payload)
    if created is None:
        raise XeroAccountWriteError("Xero did not return the created account", status_code=502)
    row = await upsert_account_from_xero_payload(
        db,
        tenant_id=tenant_id,
        integration_id=integration.id,
        xero_tenant_id=xero_tenant_id,
        account=created,
    )
    if row is None:
        raise XeroAccountWriteError("Could not store the Xero account", status_code=502)
    return row


async def update_account_in_xero(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    xero_account_id: str,
    *,
    code: str,
    name: str,
    xero_type: str,
) -> XeroAccount:
    integration, xero_tenant_id = await require_xero_ready(db, tenant_id)
    existing = await get_xero_account(db, tenant_id, xero_tenant_id, xero_account_id)
    if existing is None:
        raise XeroAccountWriteError("Xero account not found", status_code=404)
    if is_system_xero_account(existing):
        raise XeroAccountWriteError("This is a default Xero account and cannot be changed.")
    xero_type = xero_type.strip().upper()
    if xero_type == "BANK":
        raise XeroAccountWriteError(
            "Xero bank accounts need a bank account number. Use Current Asset, or edit the bank account in Xero."
        )
    client = XeroApiClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)
    body = {
        "AccountID": xero_account_id,
        "Code": _code_ok(code),
        "Name": _name_ok(name),
        "Type": xero_type,
    }
    try:
        payload = await client.post_json("Accounts", json_body={"Accounts": [body]})
    except XeroApiError as exc:
        raise XeroAccountWriteError(
            exc.message or "Xero rejected the account update",
            status_code=exc.status_code or 502,
        ) from exc
    updated = _first_account(payload)
    if updated is None:
        updated = {
            **body,
            "Class": existing.account_class,
            "Status": existing.status or "ACTIVE",
            "SystemAccount": _parse_payload(existing.raw_payload_json).get("SystemAccount"),
        }
    row = await upsert_account_from_xero_payload(
        db,
        tenant_id=tenant_id,
        integration_id=integration.id,
        xero_tenant_id=xero_tenant_id,
        account=updated,
    )
    if row is None:
        raise XeroAccountWriteError("Could not store the Xero account", status_code=502)
    return row


async def delete_account_in_xero(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    xero_account_id: str,
) -> XeroAccount:
    integration, xero_tenant_id = await require_xero_ready(db, tenant_id)
    existing = await get_xero_account(db, tenant_id, xero_tenant_id, xero_account_id)
    if existing is None:
        raise XeroAccountWriteError("Xero account not found", status_code=404)
    if is_system_xero_account(existing):
        raise XeroAccountWriteError("This is a default Xero account and cannot be deleted.")
    client = XeroApiClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)
    body = {"Accounts": [{"AccountID": xero_account_id, "Status": "DELETED"}]}
    try:
        await client.post_json("Accounts", json_body=body)
    except XeroApiError:
        try:
            await client.post_json(
                "Accounts",
                json_body={"Accounts": [{"AccountID": xero_account_id, "Status": "ARCHIVED"}]},
            )
        except XeroApiError as exc:
            raise XeroAccountWriteError(
                exc.message or "Xero could not delete this account",
                status_code=exc.status_code or 502,
            ) from exc
    existing.status = "DELETED"
    existing.sync_status = _SYNC_INACTIVE
    existing.last_synced_at = _now()
    await db.flush()
    del integration
    return existing


def ledger_type_for_row(row: XeroAccount) -> str:
    return ledger_type_for_xero(account_type=row.account_type, account_class=row.account_class)
