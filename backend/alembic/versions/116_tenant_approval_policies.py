"""Per-tenant approval policy & privileges in Postgres.

Revision ID: 116
Revises: 115

Imports legacy filesystem policies when present:
  uploads/tenants/{uuid}/approval_policy.json
  uploads/approval_policy.json orgs map
"""

from __future__ import annotations

import json
import uuid as uuid_lib
from pathlib import Path
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "116"
down_revision: Union[str, None] = "115"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _collect_tenant_policy_files() -> list[tuple[str, Path]]:
    roots = [
        Path("./uploads/tenants"),
        Path("./data/uploads/tenants"),
        Path("/app/uploads/tenants"),
    ]
    found: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.glob("*/approval_policy.json"):
            try:
                tid = str(uuid_lib.UUID(path.parent.name))
            except ValueError:
                continue
            found.setdefault(tid, path)
    return list(found.items())


def _collect_legacy_org_policies() -> list[tuple[str, dict[str, Any]]]:
    candidates = [
        Path("./uploads/approval_policy.json"),
        Path("./data/uploads/approval_policy.json"),
        Path("/app/uploads/approval_policy.json"),
    ]
    out: list[tuple[str, dict[str, Any]]] = []
    for path in candidates:
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        orgs = raw.get("orgs") if isinstance(raw, dict) else None
        if not isinstance(orgs, dict):
            continue
        for key, policy in orgs.items():
            if not isinstance(policy, dict):
                continue
            try:
                tid = str(uuid_lib.UUID(str(key)))
            except ValueError:
                continue
            out.append((tid, policy))
        break
    return out


def _import_policies(conn) -> None:
    payloads: dict[str, dict[str, Any]] = {}
    for tid, policy in _collect_legacy_org_policies():
        payloads.setdefault(tid, policy)
    for tid, path in _collect_tenant_policy_files():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(raw, dict) and "orgs" not in raw:
            payloads[tid] = raw

    for tenant_id, config in payloads.items():
        exists = conn.execute(
            sa.text("SELECT 1 FROM tenants WHERE id = CAST(:tid AS uuid)"),
            {"tid": tenant_id},
        ).fetchone()
        if exists is None:
            continue
        conn.execute(
            sa.text(
                """
                INSERT INTO tenant_approval_policies
                    (tenant_id, config, schema_version, updated_at)
                VALUES
                    (CAST(:tenant_id AS uuid), CAST(:config AS jsonb), 1, now())
                ON CONFLICT (tenant_id) DO NOTHING
                """
            ),
            {
                "tenant_id": tenant_id,
                "config": json.dumps(config),
            },
        )


def upgrade() -> None:
    op.create_table(
        "tenant_approval_policies",
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
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("tenant_id"),
    )

    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(
            sa.text("ALTER TABLE tenant_approval_policies ENABLE ROW LEVEL SECURITY")
        )
        conn.execute(
            sa.text(
                """
                CREATE POLICY tenant_isolation ON tenant_approval_policies
                  USING (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  )
                  WITH CHECK (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  )
                """
            )
        )
        _import_policies(conn)


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(
            sa.text(
                "DROP POLICY IF EXISTS tenant_isolation ON tenant_approval_policies"
            )
        )
    op.drop_table("tenant_approval_policies")
