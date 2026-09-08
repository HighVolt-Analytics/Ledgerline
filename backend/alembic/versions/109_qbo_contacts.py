"""Cached QuickBooks Online vendors and customers.

Revision ID: 109
Revises: 108
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "109"
down_revision: Union[str, None] = "108"
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
    if inspect(conn).has_table("qbo_contacts"):
        return
    op.create_table(
        "qbo_contacts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("accounting_integration_id", sa.Integer(), nullable=False),
        sa.Column("realm_id", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("qbo_entity_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=True),
        sa.Column("last_name", sa.String(length=128), nullable=True),
        sa.Column("email_address", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("tax_number", sa.String(length=64), nullable=True),
        sa.Column("is_supplier", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_customer", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("mapping_status", sa.String(length=32), nullable=False, server_default="unmapped"),
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
            "entity_type",
            "qbo_entity_id",
            name="uq_qbo_contacts_tenant_realm_entity",
        ),
    )
    op.create_index("ix_qbo_contacts_tenant_id", "qbo_contacts", ["tenant_id"])
    op.create_index("ix_qbo_contacts_name", "qbo_contacts", ["name"])
    op.create_index("ix_qbo_contacts_sync_status", "qbo_contacts", ["sync_status"])
    _enable_tenant_rls(conn, "qbo_contacts")


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql" and inspect(conn).has_table("qbo_contacts"):
        conn.execute(sa.text('DROP POLICY IF EXISTS tenant_isolation ON "qbo_contacts"'))
    op.drop_table("qbo_contacts")
