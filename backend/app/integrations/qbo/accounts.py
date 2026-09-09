"""QuickBooks chart of accounts: cache sync, create, update, inactivate, subaccounts."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.qbo.account_types import (
    CREATE_BLOCKED_ACCOUNT_TYPES,
    LOCKED_ACCOUNT_SUBTYPES,
    LOCKED_ACCOUNT_TYPES,
    default_account_subtype,
    ledger_type_for_qbo,
)
from app.integrations.qbo.client import QboApiClient, QboApiError
from app.integrations.qbo.store import require_qbo_ready
from app.integrations.xero.sync_counts import EntitySyncCounters, payload_hash
from app.models.qbo_account import SOURCE_SYSTEM_QBO, QboAccount
from app.schemas.rule_book_config import SubLedgerEntry
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SYNC_ACTIVE = "active"
_SYNC_INACTIVE = "inactive"
_PAGE_SIZE = 1000
_MAX_PAGES = 50
_NAME_MAX = 100


class QboAccountWriteError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _parse_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _ref_value(block: Any) -> str | None:
    if isinstance(block, dict):
        text = str(block.get("value") or "").strip()
        return text or None
    return None


def _name_ok(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise QboAccountWriteError("Account name is required")
    return cleaned[:_NAME_MAX]


def _acct_num_for_api(code: str | None) -> str | None:
    cleaned = (code or "").strip()
    if not cleaned or cleaned.upper().startswith("Q-"):
        return None
    return cleaned[:64]


def local_code_for_qbo(row: QboAccount) -> str:
    if (row.acct_num or "").strip():
        return row.acct_num.strip()[:32]
    return f"Q-{row.qbo_account_id}"


def is_system_qbo_account(row: QboAccount) -> bool:
    if (row.account_type or "").strip() in LOCKED_ACCOUNT_TYPES:
        return True
    if (row.account_sub_type or "").strip() in LOCKED_ACCOUNT_SUBTYPES:
        return True
    return False


def is_top_level_qbo_account(row: QboAccount) -> bool:
    return not row.sub_account and not (row.parent_ref or "").strip()


async def _query_all(client: QboApiClient, entity_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = 1
    while True:
        statement = (
            f"SELECT * FROM {entity_name} STARTPOSITION {start} MAXRESULTS {_PAGE_SIZE}"
        )
        payload = await client.query(statement)
        query = payload.get("QueryResponse") or {}
        batch = _as_list(query.get(entity_name))
        rows.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break
        start += _PAGE_SIZE
        if start > _PAGE_SIZE * _MAX_PAGES:
            break
    return rows


def _fields_from_account(account: dict[str, Any]) -> dict[str, Any]:
    parent = _ref_value(account.get("ParentRef"))
    currency = _ref_value(account.get("CurrencyRef")) or str(account.get("CurrencyRef") or "")[:8]
    if currency and len(currency) > 8:
        currency = None
    return {
        "name": str(account.get("Name") or "")[:255] or None,
        "acct_num": str(account.get("AcctNum") or "")[:64] or None,
        "fully_qualified_name": str(account.get("FullyQualifiedName") or "")[:512] or None,
        "account_type": str(account.get("AccountType") or "")[:64] or None,
        "account_sub_type": str(account.get("AccountSubType") or "")[:64] or None,
        "classification": str(account.get("Classification") or "")[:64] or None,
        "parent_ref": parent,
        "sub_account": bool(account.get("SubAccount", False) or parent),
        "active": bool(account.get("Active", True)),
        "currency_code": currency or None,
        "description": str(account.get("Description") or "")[:512] or None,
    }


async def upsert_account_from_qbo_payload(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    integration_id: int,
    realm_id: str,
    account: dict[str, Any],
) -> QboAccount | None:
    account_id = str(account.get("Id") or "").strip()
    if not account_id:
        return None
    now = _now()
    hash_value = payload_hash(account)
    fields = _fields_from_account(account)
    sync_status = _SYNC_ACTIVE if fields["active"] else _SYNC_INACTIVE
    existing = (
        await db.execute(
            select(QboAccount).where(
                QboAccount.tenant_id == tenant_id,
                QboAccount.realm_id == realm_id,
                QboAccount.qbo_account_id == account_id,
            )
        )
    ).scalar_one_or_none()
    extras = {
        "sync_status": sync_status,
        "payload_hash": hash_value,
        "raw_payload_json": json.dumps(account, default=str),
        "last_seen_at": now,
        "last_synced_at": now,
    }
    if existing is None:
        row = QboAccount(
            tenant_id=tenant_id,
            accounting_integration_id=integration_id,
            realm_id=realm_id,
            qbo_account_id=account_id,
            source_system=SOURCE_SYSTEM_QBO,
            **fields,
            **extras,
        )
        db.add(row)
        await db.flush()
        return row
    for key, value in {**fields, **extras}.items():
        setattr(existing, key, value)
    await db.flush()
    return existing


async def list_cached_qbo_accounts(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    realm_id: str,
) -> list[QboAccount]:
    return list(
        (
            await db.execute(
                select(QboAccount)
                .where(
                    QboAccount.tenant_id == tenant_id,
                    QboAccount.realm_id == realm_id,
                )
                .order_by(QboAccount.acct_num.asc().nulls_last(), QboAccount.name.asc())
            )
        ).scalars().all()
    )


async def list_active_qbo_accounts(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    realm_id: str,
) -> list[QboAccount]:
    return [
        row
        for row in await list_cached_qbo_accounts(db, tenant_id, realm_id)
        if row.active and (row.sync_status or "") == _SYNC_ACTIVE
    ]


def _name_key(value: str | None) -> str:
    return (value or "").strip().casefold()


def is_qbo_duplicate_name_error(message: str) -> bool:
    text = (message or "").casefold()
    return "duplicate" in text and "name" in text


def find_reusable_qbo_account(
    rows: list[QboAccount],
    *,
    name: str,
    code: str | None = None,
    parent_id: str | None = None,
) -> tuple[QboAccount | None, QboAccount | None]:
    """Return (reuse_row, name_conflict_row).

    QBO account names are unique in the company, including subaccounts and inactive rows.
    A new local code can still collide with an existing Name.
    """
    code_key = (code or "").strip().upper()
    if code_key and not code_key.startswith("Q-"):
        for row in rows:
            if (row.acct_num or "").strip().upper() == code_key:
                return row, None
    wanted = _name_key(name)
    if not wanted:
        return None, None
    named = [row for row in rows if _name_key(row.name) == wanted]
    if not named:
        return None, None
    parent = (parent_id or "").strip()
    if parent:
        for row in named:
            if (row.parent_ref or "").strip() == parent:
                return row, None
        return None, named[0]
    for row in named:
        if is_top_level_qbo_account(row):
            return row, None
    return None, named[0]


def _duplicate_name_message(name: str, existing: QboAccount | None) -> str:
    where = (existing.fully_qualified_name or existing.name or name).strip() if existing else name
    status = ""
    if existing is not None and not existing.active:
        status = " (inactive)"
    return (
        f"QuickBooks already has an account named {name.strip()!r} as {where!r}{status}. "
        "Names must be unique in the company, including subaccounts. "
        "Use a different name, or sync/pull that QuickBooks account instead of creating a new one."
    )


async def get_qbo_account(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    realm_id: str,
    qbo_account_id: str,
) -> QboAccount | None:
    return (
        await db.execute(
            select(QboAccount).where(
                QboAccount.tenant_id == tenant_id,
                QboAccount.realm_id == realm_id,
                QboAccount.qbo_account_id == qbo_account_id,
            )
        )
    ).scalar_one_or_none()


def children_of(parent_id: str, rows: list[QboAccount], *, active_only: bool = True) -> list[QboAccount]:
    wanted = parent_id.strip()
    return [
        row
        for row in rows
        if (row.parent_ref or "").strip() == wanted and (row.active if active_only else True)
    ]


def sub_ledgers_from_children(children: list[QboAccount]) -> list[SubLedgerEntry]:
    out: list[SubLedgerEntry] = []
    for child in children:
        name = (child.name or "").strip()
        if not name:
            continue
        out.append(
            SubLedgerEntry(
                code=local_code_for_qbo(child),
                name=name[:128],
                origin="manual",
            )
        )
    return out


async def sync_accounts_from_qbo(db: AsyncSession, tenant_id: uuid.UUID) -> EntitySyncCounters:
    integration, realm_id = await require_qbo_ready(db, tenant_id)
    client = QboApiClient(db=db, tenant_id=tenant_id, realm_id=realm_id)
    try:
        remote = await _query_all(client, "Account")
    except QboApiError as exc:
        raise QboAccountWriteError(
            exc.message or "Could not fetch accounts from QuickBooks",
            status_code=exc.status_code or 502,
        ) from exc
    counters = EntitySyncCounters()
    seen: set[str] = set()
    for account in remote:
        account_id = str(account.get("Id") or "").strip()
        if not account_id:
            continue
        counters.fetched += 1
        seen.add(account_id)
        before = await get_qbo_account(db, tenant_id, realm_id, account_id)
        old_hash = before.payload_hash if before is not None else None
        await upsert_account_from_qbo_payload(
            db,
            tenant_id=tenant_id,
            integration_id=integration.id,
            realm_id=realm_id,
            account=account,
        )
        if before is None:
            counters.created += 1
        elif old_hash == payload_hash(account):
            counters.unchanged += 1
        else:
            counters.updated += 1
    now = _now()
    for row in (
        await db.execute(
            select(QboAccount).where(
                QboAccount.tenant_id == tenant_id,
                QboAccount.realm_id == realm_id,
                QboAccount.sync_status == _SYNC_ACTIVE,
            )
        )
    ).scalars():
        if row.qbo_account_id not in seen:
            row.sync_status = _SYNC_INACTIVE
            row.last_synced_at = now
            counters.deactivated += 1
    integration.last_successful_sync_at = now
    await db.flush()
    return counters


def _account_from_response(payload: dict[str, Any]) -> dict[str, Any] | None:
    account = payload.get("Account")
    if isinstance(account, dict):
        return account
    return None


def _sync_token(row: QboAccount) -> str:
    payload = _parse_payload(row.raw_payload_json)
    token = str(payload.get("SyncToken") or "0").strip()
    return token or "0"


def _create_body(
    *,
    name: str,
    account_type: str,
    acct_num: str | None,
    parent_id: str | None = None,
) -> dict[str, Any]:
    if account_type in CREATE_BLOCKED_ACCOUNT_TYPES:
        raise QboAccountWriteError(
            f"{account_type} accounts need extra QuickBooks fields. "
            "Create them in QuickBooks, or choose Expense / Other Current Asset."
        )
    body: dict[str, Any] = {
        "Name": _name_ok(name),
        "AccountType": account_type,
        "AccountSubType": default_account_subtype(account_type),
    }
    if acct_num:
        body["AcctNum"] = acct_num
    if parent_id:
        body["SubAccount"] = True
        body["ParentRef"] = {"value": parent_id}
    return body


async def create_account_in_qbo(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    code: str,
    name: str,
    account_type: str,
    parent_id: str | None = None,
) -> QboAccount:
    integration, realm_id = await require_qbo_ready(db, tenant_id)
    cached = await list_cached_qbo_accounts(db, tenant_id, realm_id)
    reuse, conflict = find_reusable_qbo_account(
        cached, name=name, code=code, parent_id=parent_id
    )
    if reuse is not None:
        if is_system_qbo_account(reuse):
            raise QboAccountWriteError(_duplicate_name_message(name, reuse), status_code=409)
        return await update_account_in_qbo(
            db,
            tenant_id,
            reuse.qbo_account_id,
            code=code,
            name=name,
            account_type=account_type,
        )
    if conflict is not None:
        raise QboAccountWriteError(_duplicate_name_message(name, conflict), status_code=409)

    client = QboApiClient(db=db, tenant_id=tenant_id, realm_id=realm_id)
    body = _create_body(
        name=name,
        account_type=account_type,
        acct_num=_acct_num_for_api(code),
        parent_id=parent_id,
    )
    try:
        payload = await client.post_entity("account", body)
    except QboApiError as exc:
        if is_qbo_duplicate_name_error(exc.message):
            try:
                await sync_accounts_from_qbo(db, tenant_id)
            except Exception:
                pass
            cached = await list_cached_qbo_accounts(db, tenant_id, realm_id)
            reuse, conflict = find_reusable_qbo_account(
                cached, name=name, code=code, parent_id=parent_id
            )
            if reuse is not None:
                if is_system_qbo_account(reuse):
                    raise QboAccountWriteError(
                        _duplicate_name_message(name, reuse),
                        status_code=409,
                    ) from exc
                return await update_account_in_qbo(
                    db,
                    tenant_id,
                    reuse.qbo_account_id,
                    code=code,
                    name=name,
                    account_type=account_type,
                )
            raise QboAccountWriteError(
                _duplicate_name_message(name, conflict),
                status_code=409,
            ) from exc
        raise QboAccountWriteError(
            exc.message or "QuickBooks rejected the account",
            status_code=exc.status_code or 502,
        ) from exc
    created = _account_from_response(payload)
    if created is None:
        raise QboAccountWriteError("QuickBooks did not return the created account", status_code=502)
    row = await upsert_account_from_qbo_payload(
        db,
        tenant_id=tenant_id,
        integration_id=integration.id,
        realm_id=realm_id,
        account=created,
    )
    if row is None:
        raise QboAccountWriteError("Could not store the QuickBooks account", status_code=502)
    return row


async def update_account_in_qbo(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    qbo_account_id: str,
    *,
    code: str,
    name: str,
    account_type: str,
) -> QboAccount:
    integration, realm_id = await require_qbo_ready(db, tenant_id)
    existing = await get_qbo_account(db, tenant_id, realm_id, qbo_account_id)
    if existing is None:
        raise QboAccountWriteError("QuickBooks account not found", status_code=404)
    if is_system_qbo_account(existing):
        raise QboAccountWriteError("This is a default QuickBooks account and cannot be changed.")
    if account_type in CREATE_BLOCKED_ACCOUNT_TYPES and account_type != (existing.account_type or ""):
        raise QboAccountWriteError(
            f"Cannot change this account to {account_type} from LedgerLink. Edit it in QuickBooks."
        )
    client = QboApiClient(db=db, tenant_id=tenant_id, realm_id=realm_id)
    body: dict[str, Any] = {
        "Id": qbo_account_id,
        "SyncToken": _sync_token(existing),
        "sparse": True,
        "Name": _name_ok(name),
    }
    if not existing.active:
        body["Active"] = True
    acct_num = _acct_num_for_api(code)
    if acct_num:
        body["AcctNum"] = acct_num
    try:
        payload = await client.post_entity("account", body)
    except QboApiError as exc:
        raise QboAccountWriteError(
            exc.message or "QuickBooks rejected the account update",
            status_code=exc.status_code or 502,
        ) from exc
    updated = _account_from_response(payload)
    if updated is None:
        updated = {**_parse_payload(existing.raw_payload_json), **body, "Id": qbo_account_id}
    row = await upsert_account_from_qbo_payload(
        db,
        tenant_id=tenant_id,
        integration_id=integration.id,
        realm_id=realm_id,
        account=updated,
    )
    if row is None:
        raise QboAccountWriteError("Could not store the QuickBooks account", status_code=502)
    return row


async def inactivate_account_in_qbo(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    qbo_account_id: str,
) -> QboAccount:
    integration, realm_id = await require_qbo_ready(db, tenant_id)
    existing = await get_qbo_account(db, tenant_id, realm_id, qbo_account_id)
    if existing is None:
        raise QboAccountWriteError("QuickBooks account not found", status_code=404)
    if is_system_qbo_account(existing):
        raise QboAccountWriteError("This is a default QuickBooks account and cannot be deleted.")
    client = QboApiClient(db=db, tenant_id=tenant_id, realm_id=realm_id)
    body = {
        "Id": qbo_account_id,
        "SyncToken": _sync_token(existing),
        "sparse": True,
        "Active": False,
    }
    try:
        await client.post_entity("account", body)
    except QboApiError as exc:
        raise QboAccountWriteError(
            exc.message or "QuickBooks could not inactivate this account",
            status_code=exc.status_code or 502,
        ) from exc
    existing.active = False
    existing.sync_status = _SYNC_INACTIVE
    existing.last_synced_at = _now()
    await db.flush()
    del integration
    return existing


def ledger_type_for_row(row: QboAccount) -> str:
    return ledger_type_for_qbo(account_type=row.account_type, classification=row.classification)
