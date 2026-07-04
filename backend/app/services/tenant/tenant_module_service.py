"""Per-tenant module entitlements (super-admin toggles)."""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_db
from app.models.tenant_module import TenantModule
from app.tenant_modules import CATALOG_BY_KEY, CATALOG_KEYS, TOGGLEABLE_MODULE_KEYS


async def _module_rows(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, bool]:
    rows = (
        await session.execute(
            select(TenantModule).where(TenantModule.tenant_id == tenant_id)
        )
    ).scalars().all()
    return {row.module_key: row.is_active for row in rows}


async def enabled_modules_map(
    session: AsyncSession, tenant_id: uuid.UUID
) -> dict[str, bool]:
    """All toggleable keys. Missing DB row defaults to enabled."""
    db_active = await _module_rows(session, tenant_id)
    return {
        key: db_active.get(key, CATALOG_BY_KEY[key].default_active)
        for key in TOGGLEABLE_MODULE_KEYS
    }


async def is_module_enabled(
    session: AsyncSession, tenant_id: uuid.UUID, key: str
) -> bool:
    mod = CATALOG_BY_KEY.get(key)
    if mod is None:
        return True
    if mod.always_on:
        return True
    row = (
        await session.execute(
            select(TenantModule.is_active).where(
                TenantModule.tenant_id == tenant_id,
                TenantModule.module_key == key,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return mod.default_active
    return bool(row)


async def ensure_module_rows(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Insert missing catalog rows so super-admin UI shows the full list."""
    existing = await _module_rows(session, tenant_id)
    for key in TOGGLEABLE_MODULE_KEYS:
        if key in existing:
            continue
        mod = CATALOG_BY_KEY[key]
        session.add(
            TenantModule(
                tenant_id=tenant_id,
                module_key=key,
                is_active=mod.default_active,
            )
        )
    await session.flush()


def validate_module_keys(keys: list[str]) -> None:
    unknown = [k for k in keys if k not in CATALOG_KEYS]
    if unknown:
        raise ValueError(f"Unknown module keys: {', '.join(sorted(unknown))}")


def require_module(key: str):
    async def _guard(
        db: AsyncSession = Depends(get_db),
        ctx: AuthContext = Depends(get_auth_context),
    ) -> None:
        if not await is_module_enabled(db, ctx.tenant_id, key):
            raise HTTPException(403, f"Module disabled: {key}")

    return _guard
