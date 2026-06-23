"""Tenant rule book configs table (DB source of truth).

Revision ID: 032
Revises: 031

Imports legacy filesystem configs:
  1_config.json -> 550e8400-e29b-41d4-a716-446655440001
  2_config.json -> 550e8400-e29b-41d4-a716-446655440002
  {uuid}_config.json -> uuid
"""

from __future__ import annotations

import json
import uuid as uuid_lib
from pathlib import Path
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "032"
down_revision: Union[str, None] = "031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TESTING_UUID = "550e8400-e29b-41d4-a716-446655440001"
PLATFORM_UUID = "550e8400-e29b-41d4-a716-446655440002"

_LEGACY_INT_KEYS = {
    "1": TESTING_UUID,
    "2": PLATFORM_UUID,
}


def _strip_masters(config: dict[str, Any]) -> dict[str, Any]:
    data = dict(config)
    data.pop("vendor_masters", None)
    data.pop("employee_masters", None)
    return data


def _tenant_id_from_filename(name: str) -> str | None:
    if not name.endswith("_config.json"):
        return None
    key = name[: -len("_config.json")]
    if key in _LEGACY_INT_KEYS:
        return _LEGACY_INT_KEYS[key]
    try:
        return str(uuid_lib.UUID(key))
    except ValueError:
        return None


def _collect_rule_book_files() -> list[tuple[str, Path]]:
    """Return (tenant_uuid_str, path) for each legacy config file found."""
    roots = [
        Path("./uploads/rule_books"),
        Path("./data/uploads/rule_books"),
    ]
    found: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.glob("*_config.json"):
            tid = _tenant_id_from_filename(path.name)
            if tid is None:
                continue
            found.setdefault(tid, path)
    return list(found.items())


def _import_files_to_db(conn) -> None:
    for tenant_id, path in _collect_rule_book_files():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        config = _strip_masters(raw)
        schema_version = int(config.get("schema_version") or 1)
        conn.execute(
            sa.text(
                """
                INSERT INTO tenant_rule_book_configs
                    (tenant_id, config, schema_version, updated_at)
                VALUES
                    (CAST(:tenant_id AS uuid), CAST(:config AS jsonb), :schema_version, now())
                ON CONFLICT (tenant_id) DO NOTHING
                """
            ),
            {
                "tenant_id": tenant_id,
                "config": json.dumps(config),
                "schema_version": schema_version,
            },
        )


def upgrade() -> None:
    op.create_table(
        "tenant_rule_book_configs",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("config", JSONB().with_variant(sa.JSON(), "sqlite"), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("tenant_id"),
    )

    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(sa.text("ALTER TABLE tenant_rule_book_configs ENABLE ROW LEVEL SECURITY"))
        conn.execute(
            sa.text(
                """
                CREATE POLICY tenant_isolation ON tenant_rule_book_configs
                  USING (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  )
                  WITH CHECK (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  )
                """
            )
        )
        _import_files_to_db(conn)


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(
            sa.text("DROP POLICY IF EXISTS tenant_isolation ON tenant_rule_book_configs")
        )
    op.drop_table("tenant_rule_book_configs")
