"""Cached QuickBooks Online tax codes.

Revision ID: 110
Revises: 109
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "110"
down_revision: Union[str, None] = "109"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _enable_tenant_rls(conn, table: str) -> None:
    if conn.dialect.name != "postgresql":
        return
    conn.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
    conn.execute(
        sa.text(
            f"""
            CREATE POLICY tenant_isolation ON "{table}"
              USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
              )
              WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
              )
            """
        )
    )


def upgrade() -> None:
    conn = op.get_bind()
    if inspect(conn).has_table("qbo_tax_codes"):
        return
    op.create_table(
        "qbo_tax_codes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("accounting_integration_id", sa.Integer(), nullable=False),
        sa.Column("realm_id", sa.String(length=128), nullable=False),
        sa.Column("qbo_tax_code_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("taxable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("purchase_rate", sa.Numeric(12, 6), nullable=True),
        sa.Column("sales_rate", sa.Numeric(12, 6), nullable=True),
        sa.Column("source_system", sa.String(length=32), nullable=False, server_default="quickbooks"),
        sa.Column("sync_status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.Column("raw_payload_json", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["accounting_integration_id"],
            ["accounting_integrations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "realm_id",
            "qbo_tax_code_id",
            name="uq_qbo_tax_codes_tenant_realm_code",
        ),
    )
    op.create_index("ix_qbo_tax_codes_tenant_id", "qbo_tax_codes", ["tenant_id"])
    op.create_index("ix_qbo_tax_codes_name", "qbo_tax_codes", ["name"])
    op.create_index("ix_qbo_tax_codes_sync_status", "qbo_tax_codes", ["sync_status"])
    _enable_tenant_rls(conn, "qbo_tax_codes")


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql" and inspect(conn).has_table("qbo_tax_codes"):
        conn.execute(sa.text('DROP POLICY IF EXISTS tenant_isolation ON "qbo_tax_codes"'))
    op.drop_table("qbo_tax_codes")
