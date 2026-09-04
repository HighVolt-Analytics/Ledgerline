"""Ensure document currencies exist on the connected Xero organisation."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.xero.client import XeroApiClient, XeroApiError
from app.integrations.xero.store import require_xero_ready
from app.integrations.xero.sync_counts import payload_hash
from app.models.invoice import Invoice
from app.models.xero_currency import SOURCE_SYSTEM_XERO, XeroCurrency
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SYNC_ACTIVE = "active"


async def _local_currency(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    xero_tenant_id: str,
    code: str,
) -> XeroCurrency | None:
    return (
        await db.execute(
            select(XeroCurrency).where(
                XeroCurrency.tenant_id == tenant_id,
                XeroCurrency.xero_tenant_id == xero_tenant_id,
                XeroCurrency.code == code,
                XeroCurrency.sync_status == _SYNC_ACTIVE,
            )
        )
    ).scalar_one_or_none()


async def _persist_currency(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    integration_id: int,
    xero_tenant_id: str,
    payload: dict[str, Any],
) -> XeroCurrency | None:
    code = str(payload.get("Code") or "").strip().upper()
    if not code:
        return None
    now = datetime.now(timezone.utc)
    hash_value = payload_hash(payload)
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
        existing = XeroCurrency(
            tenant_id=tenant_id,
            accounting_integration_id=integration_id,
            xero_tenant_id=xero_tenant_id,
            code=code,
            description=str(payload.get("Description") or "")[:255] or None,
            source_system=SOURCE_SYSTEM_XERO,
            sync_status=_SYNC_ACTIVE,
            payload_hash=hash_value,
            raw_payload_json=json.dumps(payload, default=str),
            last_seen_at=now,
            last_synced_at=now,
        )
        db.add(existing)
    else:
        existing.description = str(payload.get("Description") or "")[:255] or None
        existing.sync_status = _SYNC_ACTIVE
        existing.payload_hash = hash_value
        existing.raw_payload_json = json.dumps(payload, default=str)
        existing.last_seen_at = now
        existing.last_synced_at = now
    await db.flush()
    return existing


async def ensure_xero_currency(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    code: str,
) -> XeroCurrency | None:
    """Return an active org currency, adding it on Xero when the plan allows."""
    code = (code or "").strip().upper()
    if not code:
        return None
    integration, xero_tenant_id = await require_xero_ready(db, tenant_id)
    existing = await _local_currency(
        db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id, code=code
    )
    if existing is not None:
        return existing

    client = XeroApiClient(db=db, tenant_id=tenant_id, xero_tenant_id=xero_tenant_id)
    try:
        remote = await client.get_currencies()
    except XeroApiError:
        logger.warning(
            "xero_currency_list_failed",
            tenant_id=str(tenant_id),
            code=code,
            exc_info=True,
        )
        remote = []
    for row in remote:
        if str(row.get("Code") or "").strip().upper() == code:
            return await _persist_currency(
                db,
                tenant_id=tenant_id,
                integration_id=integration.id,
                xero_tenant_id=xero_tenant_id,
                payload=row,
            )

    try:
        payload = await client.put_json("Currencies", json_body={"Code": code})
    except XeroApiError as exc:
        logger.warning(
            "xero_currency_add_failed",
            tenant_id=str(tenant_id),
            code=code,
            status_code=exc.status_code,
            error=exc.message,
        )
        return None

    created = None
    if isinstance(payload, dict):
        currencies = payload.get("Currencies")
        if isinstance(currencies, list) and currencies and isinstance(currencies[0], dict):
            created = currencies[0]
        elif payload.get("Code"):
            created = payload
    if not isinstance(created, dict):
        created = {"Code": code}
    return await _persist_currency(
        db,
        tenant_id=tenant_id,
        integration_id=integration.id,
        xero_tenant_id=xero_tenant_id,
        payload=created,
    )


async def ensure_invoice_xero_currency(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
) -> None:
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None or invoice.tenant_id != tenant_id:
        return
    await ensure_xero_currency(db, tenant_id=tenant_id, code=invoice.currency or "")
