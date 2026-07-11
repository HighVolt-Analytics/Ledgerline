"""Backfill missing starter control accounts on legacy tenant COAs.

Revision ID: 065
Revises: 064
"""

from __future__ import annotations

import json
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.schemas.rule_book_config import PostingDefaults, validate_rule_book_config_payload
from app.services.master_data.starter_chart_of_accounts import merge_missing_starter_accounts
from app.services.rule_book.account_mapper import coa_functional_for_journaling

revision: str = "065"
down_revision: Union[str, None] = "064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _merge_config_coa(config: dict[str, Any], *, country: str | None) -> dict[str, Any]:
    payload = validate_rule_book_config_payload(dict(config))
    if coa_functional_for_journaling(payload):
        return dict(config)

    posting = payload.posting_defaults or PostingDefaults.for_country(country)
    merged = merge_missing_starter_accounts(
        list(payload.chart_of_accounts),
        country,
        posting_defaults=posting,
    )
    if len(merged) == len(payload.chart_of_accounts):
        return dict(config)

    data = dict(config)
    data["posting_defaults"] = posting.model_dump()
    data["chart_of_accounts"] = [entry.model_dump() for entry in merged]
    return validate_rule_book_config_payload(data).model_dump()


def upgrade() -> None:
    conn = op.get_bind()
    tenant_rows = conn.execute(
        sa.text("SELECT id, settings_json FROM tenants WHERE is_active = true")
    ).fetchall()
    country_by_tenant = {
        row[0]: (row[1] or {}).get("country") if isinstance(row[1], dict) else None
        for row in tenant_rows
    }

    config_rows = conn.execute(
        sa.text("SELECT tenant_id, config FROM tenant_rule_book_configs")
    ).fetchall()
    for tenant_id, config_raw in config_rows:
        if isinstance(config_raw, str):
            config_raw = json.loads(config_raw)
        if not isinstance(config_raw, dict):
            continue
        country = country_by_tenant.get(tenant_id)
        merged = _merge_config_coa(config_raw, country=country)
        if merged == config_raw:
            continue
        conn.execute(
            sa.text(
                "UPDATE tenant_rule_book_configs SET config = :config WHERE tenant_id = :tenant_id"
            ),
            {"config": json.dumps(merged), "tenant_id": tenant_id},
        )


def downgrade() -> None:
    pass
