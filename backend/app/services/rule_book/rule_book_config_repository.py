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
from app.schemas.rule_book_config import (
    PostingDefaults,
    RuleBookConfigPayload,
    TeamExpensePostingDefaults,
    validate_rule_book_config_payload,
)
from app.services.rule_book.account_mapper import coa_functional_for_journaling
from app.services.master_data.starter_chart_of_accounts import (
    STAFF_ADVANCE_ACCOUNT,
    build_starter_chart_of_accounts,
    merge_missing_starter_accounts,
)
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
    # Starter COA includes Staff Advance — bind advance parent only for greenfield seed.
    team_posting = TeamExpensePostingDefaults.for_posting_defaults(posting)
    data["team_expense_posting"] = team_posting.model_copy(
        update={"default_advance_parent_ledger": STAFF_ADVANCE_ACCOUNT}
    ).model_dump()
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


def _find_staff_advance_coa_name(entries: list[Any]) -> str | None:
    """Return the exact COA account name for Staff Advance when present."""
    target = (STAFF_ADVANCE_ACCOUNT or "").strip().lower().rstrip(".,;:")
    for entry in entries:
        name = getattr(entry, "name", None)
        if name is None and isinstance(entry, dict):
            name = entry.get("name")
        text = str(name or "").strip()
        if text and text.lower().rstrip(".,;:") == target:
            return text
    return None


def ensure_team_advance_parent_in_config(data: dict[str, Any]) -> dict[str, Any]:
    """Bind empty advance parent to Staff Advance when that ledger exists in COA.

    Also normalizes a trailing-punctuation COA label (``Staff Advance.``) back to
    the canonical starter name when safe.
    """
    out = deepcopy(data)
    coa = list(out.get("chart_of_accounts") or [])
    renamed = False
    for entry in coa:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if name.rstrip(".,;:") == STAFF_ADVANCE_ACCOUNT and name != STAFF_ADVANCE_ACCOUNT:
            entry["name"] = STAFF_ADVANCE_ACCOUNT
            renamed = True
    if renamed:
        out["chart_of_accounts"] = coa

    team = dict(out.get("team_expense_posting") or {})
    current = str(team.get("default_advance_parent_ledger") or "").strip()
    staff_name = _find_staff_advance_coa_name(coa)
    if staff_name and (
        not current
        or current.rstrip(".,;:") == STAFF_ADVANCE_ACCOUNT
    ):
        if current != staff_name:
            team["default_advance_parent_ledger"] = staff_name
            out["team_expense_posting"] = team
    return out


async def upgrade_tenant_coa_if_needed(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> bool:
    """Merge missing starter control accounts and bind empty team advance parent.

    Idempotent. Still merges thin COAs that cannot journal; also ensures Staff Advance
    exists and ``team_expense_posting.default_advance_parent_ledger`` is bound when empty.
    """
    raw = await fetch_config_dict(session, tenant_id)
    if raw is None:
        return False

    config = validate_rule_book_config_payload(raw)
    country = await _resolve_country_for_tenant(session, tenant_id)
    merged_entries = list(config.chart_of_accounts)
    if not coa_functional_for_journaling(config) or _find_staff_advance_coa_name(
        merged_entries
    ) is None:
        merged_entries = merge_missing_starter_accounts(
            merged_entries,
            country,
            posting_defaults=config.posting_defaults,
        )

    data = deepcopy(raw)
    data["chart_of_accounts"] = [entry.model_dump() for entry in merged_entries]
    data = ensure_team_advance_parent_in_config(data)
    validated = validate_rule_book_config_payload(data).model_dump()
    if validated == validate_rule_book_config_payload(raw).model_dump():
        return False
    await upsert_config(session, tenant_id, validated)
    return True


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
