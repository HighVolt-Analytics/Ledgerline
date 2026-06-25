"""Tenant-scoped ORM helpers — enforce tenant_id on every row load."""

from __future__ import annotations

import uuid
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenant_ids import parse_tenant_id

T = TypeVar("T")


def coerce_tenant_uuid(tenant_id: uuid.UUID | int | str | None) -> uuid.UUID | None:
    return parse_tenant_id(tenant_id)


async def get_for_tenant(
    session: AsyncSession,
    model: type[T],
    record_id: int | uuid.UUID,
    tenant_id: uuid.UUID | int,
    *,
    tenant_column: str = "tenant_id",
) -> T | None:
    """Load a row by primary key only when it belongs to the given tenant."""
    row = await session.get(model, record_id)
    if row is None:
        return None
    row_tid = getattr(row, tenant_column, None)
    expected = coerce_tenant_uuid(tenant_id)
    if row_tid is None or expected is None or row_tid != expected:
        return None
    return row


async def select_for_tenant(
    session: AsyncSession,
    model: type[T],
    record_id: int | uuid.UUID,
    tenant_id: uuid.UUID | int,
    *,
    tenant_column: str = "tenant_id",
) -> T | None:
    """Explicit tenant-filtered select (preferred over get + post-check)."""
    expected = coerce_tenant_uuid(tenant_id)
    if expected is None:
        return None
    col = getattr(model, tenant_column)
    return (
        await session.execute(
            select(model).where(model.id == record_id, col == expected)
        )
    ).scalar_one_or_none()
