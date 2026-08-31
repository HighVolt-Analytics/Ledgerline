"""Send one canonical document to one or more adapters. v1: Xero only."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.xero.export import push_invoice_to_xero_pipeline

SUPPORTED_ADAPTERS = ("xero",)


async def send(
    canonical: dict[str, Any],
    adapters: list[str],
    *,
    db: AsyncSession | None = None,
    tenant_id: uuid.UUID | None = None,
    user_id: int = 0,
) -> dict[str, Any]:
    if not adapters:
        raise ValueError("at least one adapter is required")
    unknown = [name for name in adapters if name not in SUPPORTED_ADAPTERS]
    if unknown:
        raise ValueError(f"unsupported adapters: {unknown}")
    if db is None or tenant_id is None:
        raise ValueError("db and tenant_id are required to send")
    invoice_id = canonical.get("invoice_id") or canonical.get("source_invoice_id")
    if invoice_id is None:
        raise ValueError("canonical snapshot is missing invoice_id")

    results: dict[str, Any] = {}
    for name in adapters:
        if name == "xero":
            results[name] = await push_invoice_to_xero_pipeline(
                db,
                tenant_id=tenant_id,
                invoice_id=int(invoice_id),
                user_id=user_id,
            )
    return results
