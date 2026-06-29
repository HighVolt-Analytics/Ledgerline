"""Accounting provider OAuth connections (Xero, QuickBooks Online).

Revision ID: 049
Revises: 048
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "049"
down_revision: Union[str, None] = "048"
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
    op.create_table(
        "accounting_integrations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_tenant_id", sa.String(length=128), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.String(length=512), nullable=True),
        sa.Column("connected_by_user_id", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["connected_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "provider",
            name="uq_accounting_integrations_tenant_provider",
        ),
    )
    op.create_index(
        "ix_accounting_integrations_tenant_id",
        "accounting_integrations",
        ["tenant_id"],
    )
    op.create_index(
        "ix_accounting_integrations_provider",
        "accounting_integrations",
        ["provider"],
    )
    op.create_index(
        "ix_accounting_integrations_provider_tenant_id",
        "accounting_integrations",
        ["provider_tenant_id"],
    )

    conn = op.get_bind()
    _enable_tenant_rls(conn, "accounting_integrations")


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(
            sa.text('DROP POLICY IF EXISTS tenant_isolation ON "accounting_integrations"')
        )
    op.drop_index("ix_accounting_integrations_provider_tenant_id", table_name="accounting_integrations")
    op.drop_index("ix_accounting_integrations_provider", table_name="accounting_integrations")
    op.drop_index("ix_accounting_integrations_tenant_id", table_name="accounting_integrations")
    op.drop_table("accounting_integrations")
