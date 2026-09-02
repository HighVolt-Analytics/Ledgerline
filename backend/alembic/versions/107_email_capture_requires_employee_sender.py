"""Backfill requires_employee_sender on email_capture_rules JSON rows.

Revision ID: 107
Revises: 106
"""

from __future__ import annotations

import json
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "107"
down_revision: Union[str, None] = "106"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _infer_requires_employee_sender(rule: dict[str, Any]) -> bool:
    action = rule.get("action") if isinstance(rule.get("action"), dict) else {}
    route = str(action.get("route_to") or "").strip()
    rule_id = str(rule.get("id") or "").strip()
    name = str(rule.get("name") or "").strip().lower()
    if route == "Team Expenses":
        return True
    if rule_id in {"ec-default"}:
        return True
    if rule_id == "ec-employee-bypass":
        return True
    if name in {
        "all mailbox attachments",
        "catch all",
        "catch-all",
        "all attachments",
    }:
        return True
    return False


def _backfill_rules(config: dict[str, Any]) -> dict[str, Any]:
    rules = config.get("email_capture_rules")
    if not isinstance(rules, list):
        return config
    changed = False
    next_rules: list[Any] = []
    for row in rules:
        if not isinstance(row, dict):
            next_rules.append(row)
            continue
        if row.get("requires_employee_sender") is not None:
            next_rules.append(row)
            continue
        merged = dict(row)
        merged["requires_employee_sender"] = _infer_requires_employee_sender(row)
        next_rules.append(merged)
        changed = True
    if not changed:
        return config
    out = dict(config)
    out["email_capture_rules"] = next_rules
    return out


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT tenant_id, config FROM tenant_rule_book_configs")
    ).fetchall()
    for tenant_id, config_raw in rows:
        if isinstance(config_raw, str):
            config_raw = json.loads(config_raw)
        if not isinstance(config_raw, dict):
            continue
        merged = _backfill_rules(config_raw)
        if merged == config_raw:
            continue
        conn.execute(
            sa.text(
                "UPDATE tenant_rule_book_configs SET config = :config WHERE tenant_id = :tenant_id"
            ),
            {"config": json.dumps(merged), "tenant_id": tenant_id},
        )


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT tenant_id, config FROM tenant_rule_book_configs")
    ).fetchall()
    for tenant_id, config_raw in rows:
        if isinstance(config_raw, str):
            config_raw = json.loads(config_raw)
        if not isinstance(config_raw, dict):
            continue
        rules = config_raw.get("email_capture_rules")
        if not isinstance(rules, list):
            continue
        stripped = []
        changed = False
        for row in rules:
            if isinstance(row, dict) and "requires_employee_sender" in row:
                copy = dict(row)
                copy.pop("requires_employee_sender", None)
                stripped.append(copy)
                changed = True
            else:
                stripped.append(row)
        if not changed:
            continue
        merged = dict(config_raw)
        merged["email_capture_rules"] = stripped
        conn.execute(
            sa.text(
                "UPDATE tenant_rule_book_configs SET config = :config WHERE tenant_id = :tenant_id"
            ),
            {"config": json.dumps(merged), "tenant_id": tenant_id},
        )
