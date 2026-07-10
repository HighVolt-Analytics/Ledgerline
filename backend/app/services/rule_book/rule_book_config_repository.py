"""Postgres persistence for per-tenant rule book configs."""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.tenant import Tenant
from app.models.tenant_rule_book_config import TenantRuleBookConfig
from app.schemas.rule_book_config import PostingDefaults, RuleBookConfigPayload
from app.services.master_data.starter_chart_of_accounts import build_starter_chart_of_accounts
from app.tenant_settings import tenant_country


def _base_template_config_dict() -> dict[str, Any]:
    template = Path(get_settings().rule_book_config_path)
    if template.is_file():
        with template.open(encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            data = deepcopy(raw)
            data.pop("vendor_masters", None)
            data.pop("employee_masters", None)
            return data
    return RuleBookConfigPayload().model_dump()


def _default_config_dict_for_country(country_code: str | None) -> dict[str, Any]:
    data = _base_template_config_dict()
    posting = PostingDefaults.for_country(country_code)
    data["posting_defaults"] = posting.model_dump()
    data["chart_of_accounts"] = [
        entry.model_dump()
        for entry in build_starter_chart_of_accounts(country_code, posting_defaults=posting)
    ]
    return data


def _schema_version_from_config(config: dict[str, Any]) -> int:
    try:
        return int(config.get("schema_version") or 1)
    except (TypeError, ValueError):
        return 1


async def _resolve_country_for_tenant(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> str | None:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        return None
    return tenant_country(tenant)


async def fetch_config_dict(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> dict[str, Any] | None:
    row = await session.get(TenantRuleBookConfig, tenant_id)
    if row is None:
        return None
    return deepcopy(row.config)


async def ensure_default_config(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> dict[str, Any]:
    existing = await fetch_config_dict(session, tenant_id)
    if existing is not None:
        return existing

    country = await _resolve_country_for_tenant(session, tenant_id)
    config = _default_config_dict_for_country(country)
    row = TenantRuleBookConfig(
        tenant_id=tenant_id,
        config=config,
        schema_version=_schema_version_from_config(config),
    )
    session.add(row)
    await session.flush()
    return deepcopy(config)


async def upsert_config(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    config: dict[str, Any],
    *,
    updated_by_user_id: int | None = None,
) -> None:
    data = deepcopy(config)
    data.pop("vendor_masters", None)
    data.pop("employee_masters", None)
    schema_version = _schema_version_from_config(data)

    row = await session.get(TenantRuleBookConfig, tenant_id)
    if row is None:
        session.add(
            TenantRuleBookConfig(
                tenant_id=tenant_id,
                config=data,
                schema_version=schema_version,
                updated_by_user_id=updated_by_user_id,
            )
        )
    else:
        row.config = data
        row.schema_version = schema_version
        row.updated_by_user_id = updated_by_user_id
    await session.flush()
