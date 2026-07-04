"""Tenant-scoped invoice access and upload validation."""

from __future__ import annotations

import uuid

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.tenant_scoped import get_for_tenant

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


async def get_invoice_for_tenant(
    db: AsyncSession,
    invoice_id: int,
    tenant_id: uuid.UUID,
) -> Invoice:
    inv = await get_for_tenant(db, Invoice, invoice_id, tenant_id)
    if not inv:
        raise LookupError("Invoice not found")
    return inv


async def read_upload_file(
    file: UploadFile,
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> bytes:
    data = await file.read()
    if len(data) > max_bytes:
        raise ValueError(
            f"File exceeds maximum size ({max_bytes // (1024 * 1024)} MB)"
        )
    return data
