"""Dossier manual document links (UI-only overlay).

Revision ID: 034
Revises: 033
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "034"
down_revision: Union[str, None] = "033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dossier_manual_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("anchor_invoice_id", sa.Integer(), nullable=False),
        sa.Column("linked_invoice_id", sa.Integer(), nullable=False),
        sa.Column("slot_id", sa.String(length=64), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["anchor_invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["linked_invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "anchor_invoice_id",
            "linked_invoice_id",
            name="uq_dossier_manual_links_anchor_linked",
        ),
    )
    op.create_index(
        "ix_dossier_manual_links_anchor_invoice_id",
        "dossier_manual_links",
        ["anchor_invoice_id"],
    )
    op.create_index(
        "ix_dossier_manual_links_linked_invoice_id",
        "dossier_manual_links",
        ["linked_invoice_id"],
    )
    op.create_index(
        "ix_dossier_manual_links_tenant_id",
        "dossier_manual_links",
        ["tenant_id"],
    )

    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(sa.text("ALTER TABLE dossier_manual_links ENABLE ROW LEVEL SECURITY"))
        conn.execute(
            sa.text(
                """
                CREATE POLICY tenant_isolation ON dossier_manual_links
                  USING (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  )
                  WITH CHECK (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  )
                """
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(
            sa.text("DROP POLICY IF EXISTS tenant_isolation ON dossier_manual_links")
        )
    op.drop_index("ix_dossier_manual_links_tenant_id", table_name="dossier_manual_links")
    op.drop_index("ix_dossier_manual_links_linked_invoice_id", table_name="dossier_manual_links")
    op.drop_index("ix_dossier_manual_links_anchor_invoice_id", table_name="dossier_manual_links")
    op.drop_table("dossier_manual_links")
