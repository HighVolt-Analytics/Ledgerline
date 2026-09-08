"""Add bank account_number + pending_bank_accounts queue.

Revision ID: 113
Revises: 112
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "113"
down_revision: Union[str, None] = "112"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _enable_rls(conn, table: str) -> None:
    if conn.dialect.name != "postgresql":
        return
    conn.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
    conn.execute(sa.text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
    conn.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = 'public'
                  AND tablename = '{table}'
                  AND policyname = 'tenant_isolation'
              ) THEN
                CREATE POLICY tenant_isolation ON "{table}"
                  USING (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  )
                  WITH CHECK (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  );
              END IF;
            END $$;
            """
        )
    )


def _disable_rls(conn, table: str) -> None:
    if conn.dialect.name != "postgresql":
        return
    conn.execute(sa.text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"'))
    conn.execute(sa.text(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY'))
    conn.execute(sa.text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    json_type = sa.JSON().with_variant(JSONB(astext_type=sa.Text()), "postgresql")

    bank_cols = {c["name"] for c in inspector.get_columns("bank_accounts")}
    if "account_number" not in bank_cols:
        op.add_column(
            "bank_accounts",
            sa.Column("account_number", sa.String(length=64), nullable=True),
        )

    if not inspector.has_table("pending_bank_accounts"):
        op.create_table(
            "pending_bank_accounts",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("detected_name", sa.String(length=255), nullable=True),
            sa.Column("detected_account_number", sa.String(length=64), nullable=True),
            sa.Column("detected_currency", sa.String(length=3), nullable=True),
            sa.Column("filename", sa.String(length=512), nullable=True),
            sa.Column("file_sha256", sa.String(length=64), nullable=False),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("stored_path", sa.String(length=1024), nullable=False),
            sa.Column("extracted_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("parse_meta", json_type, nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("promoted_bank_account_id", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["promoted_bank_account_id"],
                ["bank_accounts.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_pending_bank_accounts_tenant_id",
            "pending_bank_accounts",
            ["tenant_id"],
        )
        op.create_index(
            "ix_pending_bank_accounts_status",
            "pending_bank_accounts",
            ["status"],
        )
        op.create_index(
            "ix_pending_bank_accounts_file_sha256",
            "pending_bank_accounts",
            ["tenant_id", "file_sha256"],
        )

    _enable_rls(conn, "pending_bank_accounts")


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    if inspector.has_table("pending_bank_accounts"):
        _disable_rls(conn, "pending_bank_accounts")
        op.drop_index("ix_pending_bank_accounts_file_sha256", table_name="pending_bank_accounts")
        op.drop_index("ix_pending_bank_accounts_status", table_name="pending_bank_accounts")
        op.drop_index("ix_pending_bank_accounts_tenant_id", table_name="pending_bank_accounts")
        op.drop_table("pending_bank_accounts")
    bank_cols = {c["name"] for c in inspector.get_columns("bank_accounts")}
    if "account_number" in bank_cols:
        op.drop_column("bank_accounts", "account_number")
