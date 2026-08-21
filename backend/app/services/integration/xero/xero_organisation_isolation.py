"""Deactivate Xero organisation-scoped master data and mappings on org switch.

Preserves historical export ledger / audit rows (no hard-delete).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting_entity_mapping import PROVIDER_XERO, AccountingEntityMapping
from app.models.xero_account import XeroAccount
from app.models.xero_contact import XeroContact
from app.models.xero_currency import XeroCurrency
from app.models.xero_tax_rate import XeroTaxRate
from app.models.xero_tracking_category import XeroTrackingCategory

_SYNC_INACTIVE = "inactive"


async def deactivate_xero_organisation_scope(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    xero_tenant_id: str,
) -> dict[str, int]:
    """Mark prior organisation mappings and master rows inactive.

    Called when the selected Xero organisation changes. Same-org reconnect
    must not call this. Export evidence and audit records are untouched.
    """
    org_id = (xero_tenant_id or "").strip()
    if not org_id:
        return {
            "mappings": 0,
            "accounts": 0,
            "contacts": 0,
            "tax_rates": 0,
            "currencies": 0,
            "tracking": 0,
        }

    counts: dict[str, int] = {}

    map_result = await db.execute(
        update(AccountingEntityMapping)
        .where(
            AccountingEntityMapping.tenant_id == tenant_id,
            AccountingEntityMapping.provider == PROVIDER_XERO,
            AccountingEntityMapping.xero_tenant_id == org_id,
            AccountingEntityMapping.is_active.is_(True),
        )
        .values(is_active=False)
    )
    counts["mappings"] = int(map_result.rowcount or 0)

    for label, model in (
        ("accounts", XeroAccount),
        ("contacts", XeroContact),
        ("tax_rates", XeroTaxRate),
        ("currencies", XeroCurrency),
    ):
        result = await db.execute(
            update(model)
            .where(
                model.tenant_id == tenant_id,
                model.xero_tenant_id == org_id,
                model.sync_status != _SYNC_INACTIVE,
            )
            .values(sync_status=_SYNC_INACTIVE)
        )
        counts[label] = int(result.rowcount or 0)

    track_result = await db.execute(
        update(XeroTrackingCategory)
        .where(
            XeroTrackingCategory.tenant_id == tenant_id,
            XeroTrackingCategory.xero_tenant_id == org_id,
            XeroTrackingCategory.sync_status != _SYNC_INACTIVE,
        )
        .values(sync_status=_SYNC_INACTIVE, is_active=False)
    )
    counts["tracking"] = int(track_result.rowcount or 0)

    await db.flush()
    return counts


async def count_active_organisation_rows(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    xero_tenant_id: str,
) -> dict[str, Any]:
    """Active master + mapping counts for one Xero organisation (test helper)."""
    org_id = (xero_tenant_id or "").strip()

    async def _count(model, *, extra=None) -> int:
        stmt = select(model).where(
            model.tenant_id == tenant_id,
            model.xero_tenant_id == org_id,
            model.sync_status == "active",
        )
        if extra is not None:
            stmt = stmt.where(extra)
        return len((await db.execute(stmt)).scalars().all())

    mappings = len(
        (
            await db.execute(
                select(AccountingEntityMapping).where(
                    AccountingEntityMapping.tenant_id == tenant_id,
                    AccountingEntityMapping.provider == PROVIDER_XERO,
                    AccountingEntityMapping.xero_tenant_id == org_id,
                    AccountingEntityMapping.is_active.is_(True),
                )
            )
        ).scalars().all()
    )
    return {
        "mappings": mappings,
        "accounts": await _count(XeroAccount),
        "contacts": await _count(XeroContact),
        "tax_rates": await _count(XeroTaxRate),
        "currencies": await _count(XeroCurrency),
        "tracking": await _count(XeroTrackingCategory),
    }
