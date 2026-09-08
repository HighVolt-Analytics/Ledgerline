"""Ensure document currencies exist on the connected QuickBooks company."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.qbo.client import QboApiClient, QboApiError
from app.integrations.qbo.store import require_qbo_ready
from app.integrations.xero.sync_counts import EntitySyncCounters, payload_hash
from app.models.invoice import Invoice
from app.models.qbo_currency import SOURCE_SYSTEM_QBO, QboCurrency
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SYNC_ACTIVE = "active"
_SYNC_INACTIVE = "inactive"


class QboCurrencyWriteError(Exception):
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


def _first_object(value: Any) -> dict[str, Any]:
    rows = _as_list(value)
    return rows[0] if rows else {}


async def _query_all(client: QboApiClient, entity_name: str) -> list[dict[str, Any]]:
    payload = await client.query(f"SELECT * FROM {entity_name}")
    query = payload.get("QueryResponse") or {}
    return _as_list(query.get(entity_name))


def _ref_code(block: Any) -> str:
    if isinstance(block, dict):
        return str(block.get("value") or "").strip().upper()
    return str(block or "").strip().upper()


async def read_currency_prefs(client: QboApiClient) -> tuple[str | None, bool]:
    """Home ISO code and whether Multicurrency is on (UI-only to enable)."""
    rows = await _query_all(client, "Preferences")
    prefs = rows[0] if rows else {}
    currency_prefs = prefs.get("CurrencyPrefs") if isinstance(prefs.get("CurrencyPrefs"), dict) else {}
    home = _ref_code(currency_prefs.get("HomeCurrency"))
    enabled = bool(currency_prefs.get("MultiCurrencyEnabled"))
    return (home or None), enabled


async def _local_currency(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    realm_id: str,
    code: str,
) -> QboCurrency | None:
    return (
        await db.execute(
            select(QboCurrency).where(
                QboCurrency.tenant_id == tenant_id,
                QboCurrency.realm_id == realm_id,
                QboCurrency.code == code,
                QboCurrency.sync_status == _SYNC_ACTIVE,
            )
        )
    ).scalar_one_or_none()


async def _persist_currency(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    integration_id: int,
    realm_id: str,
    payload: dict[str, Any],
) -> QboCurrency | None:
    code = str(payload.get("Code") or "").strip().upper()
    if not code:
        return None
    now = _now()
    hash_value = payload_hash(payload)
    existing = (
        await db.execute(
            select(QboCurrency).where(
                QboCurrency.tenant_id == tenant_id,
                QboCurrency.realm_id == realm_id,
                QboCurrency.code == code,
            )
        )
    ).scalar_one_or_none()
    fields = {
        "name": str(payload.get("Name") or "")[:255] or None,
        "active": bool(payload.get("Active", True)),
        "source_system": SOURCE_SYSTEM_QBO,
        "sync_status": _SYNC_ACTIVE if bool(payload.get("Active", True)) else _SYNC_INACTIVE,
        "payload_hash": hash_value,
        "raw_payload_json": json.dumps(payload, default=str),
        "last_seen_at": now,
        "last_synced_at": now,
    }
    if existing is None:
        existing = QboCurrency(
            tenant_id=tenant_id,
            accounting_integration_id=integration_id,
            realm_id=realm_id,
            code=code,
            **fields,
        )
        db.add(existing)
    else:
        for key, value in fields.items():
            setattr(existing, key, value)
    await db.flush()
    return existing


async def sync_currencies_from_qbo(db: AsyncSession, tenant_id: uuid.UUID) -> EntitySyncCounters:
    integration, realm_id = await require_qbo_ready(db, tenant_id)
    client = QboApiClient(db=db, tenant_id=tenant_id, realm_id=realm_id)
    counters = EntitySyncCounters()
    home, _enabled = await read_currency_prefs(client)
    seen: set[str] = set()
    remote = await _query_all(client, "CompanyCurrency")
    if home and not any(str(row.get("Code") or "").strip().upper() == home for row in remote):
        remote = [{"Code": home, "Name": home, "Active": True}, *remote]
    for row in remote:
        code = str(row.get("Code") or "").strip().upper()
        if not code:
            continue
        counters.fetched += 1
        seen.add(code)
        before = await _local_currency(db, tenant_id=tenant_id, realm_id=realm_id, code=code)
        await _persist_currency(
            db,
            tenant_id=tenant_id,
            integration_id=integration.id,
            realm_id=realm_id,
            payload=row,
        )
        if before is None:
            counters.created += 1
        else:
            counters.unchanged += 1
    now = _now()
    for existing in (
        await db.execute(
            select(QboCurrency).where(
                QboCurrency.tenant_id == tenant_id,
                QboCurrency.realm_id == realm_id,
                QboCurrency.sync_status == _SYNC_ACTIVE,
            )
        )
    ).scalars():
        if existing.code not in seen:
            existing.sync_status = _SYNC_INACTIVE
            existing.last_synced_at = now
            counters.deactivated += 1
    await db.flush()
    return counters


async def ensure_qbo_currency(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    code: str,
) -> QboCurrency:
    """Return an active company currency, creating it in QBO when Multicurrency is on.

    Intuit does not allow turning Multicurrency on through the API. Home currency
    is always accepted. A foreign code is POSTed to CompanyCurrency only when
    Preferences.CurrencyPrefs.MultiCurrencyEnabled is already true.
    """
    iso = (code or "").strip().upper()
    if len(iso) != 3 or not iso.isalpha():
        raise QboCurrencyWriteError("Document currency must be a 3-letter ISO code.")
    integration, realm_id = await require_qbo_ready(db, tenant_id)
    cached = await _local_currency(db, tenant_id=tenant_id, realm_id=realm_id, code=iso)
    if cached is not None:
        return cached

    client = QboApiClient(db=db, tenant_id=tenant_id, realm_id=realm_id)
    try:
        home, multicurrency = await read_currency_prefs(client)
    except QboApiError as exc:
        raise QboCurrencyWriteError(
            exc.message or "Could not read QuickBooks currency settings",
            status_code=exc.status_code or 502,
        ) from exc

    if home and iso == home:
        row = await _persist_currency(
            db,
            tenant_id=tenant_id,
            integration_id=integration.id,
            realm_id=realm_id,
            payload={"Code": iso, "Name": iso, "Active": True},
        )
        if row is None:
            raise QboCurrencyWriteError("Could not store the home currency", status_code=502)
        return row

    try:
        remote = await _query_all(client, "CompanyCurrency")
    except QboApiError as exc:
        raise QboCurrencyWriteError(
            exc.message or "Could not list QuickBooks currencies",
            status_code=exc.status_code or 502,
        ) from exc
    for row in remote:
        if str(row.get("Code") or "").strip().upper() == iso:
            stored = await _persist_currency(
                db,
                tenant_id=tenant_id,
                integration_id=integration.id,
                realm_id=realm_id,
                payload=row,
            )
            if stored is None:
                raise QboCurrencyWriteError("Could not store the QuickBooks currency", status_code=502)
            return stored

    if not multicurrency:
        home_label = home or "the company home currency"
        raise QboCurrencyWriteError(
            f"QuickBooks home currency is {home_label}. Enable Multicurrency in QuickBooks "
            "(Settings → Account and settings → Advanced) before adding "
            f"{iso}. That toggle cannot be turned on through the API.",
            status_code=409,
        )

    try:
        payload = await client.post_entity("companycurrency", {"Code": iso})
    except QboApiError as exc:
        raise QboCurrencyWriteError(
            exc.message or f"QuickBooks rejected currency {iso}",
            status_code=exc.status_code or 502,
        ) from exc
    created = _first_object(payload.get("CompanyCurrency")) if isinstance(payload, dict) else {}
    if not created.get("Code"):
        created = {**created, "Code": iso, "Active": True}
    stored = await _persist_currency(
        db,
        tenant_id=tenant_id,
        integration_id=integration.id,
        realm_id=realm_id,
        payload=created,
    )
    if stored is None:
        raise QboCurrencyWriteError("Could not store the QuickBooks currency", status_code=502)
    return stored


async def ensure_invoice_qbo_currency(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
) -> QboCurrency | None:
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None or invoice.tenant_id != tenant_id:
        return None
    raw = (invoice.currency or "").strip()
    if not raw:
        raise QboCurrencyWriteError("Document currency is missing", status_code=400)
    return await ensure_qbo_currency(db, tenant_id=tenant_id, code=raw)
