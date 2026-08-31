"""Snapshot existing invoice / lines / vendor / PDF for adapters. No new extraction."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.integration.canonical_transaction_builder import (
    build_canonical_supplier_invoice,
    load_invoice_for_export,
    resolve_organisation_posting_currency,
)


async def canonical_from_invoice(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    invoice_id: int,
) -> dict[str, Any]:
    invoice = await load_invoice_for_export(
        db, tenant_id=tenant_id, invoice_id=invoice_id
    )
    currency = await resolve_organisation_posting_currency(
        db,
        tenant_id=tenant_id,
        invoice_id=invoice_id,
        document_currency=invoice.currency,
    )
    txn = build_canonical_supplier_invoice(
        invoice,
        tenant_id=tenant_id,
        posting_currency=currency or (invoice.currency or "").strip() or "AUD",
    )
    snapshot = txn.model_dump_serialisable()
    snapshot["invoice_id"] = invoice_id
    return snapshot
