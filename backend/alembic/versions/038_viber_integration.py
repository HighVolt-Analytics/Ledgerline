"""Viber Public Account connections and invoice link.

Revision ID: 043
Revises: 042
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "043"
down_revision: Union[str, None] = "042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connected_viber_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("bot_id", sa.String(length=64), nullable=False),
        sa.Column("auth_token_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "connection_status",
            sa.String(length=32),
            nullable=False,
            server_default="connected",
        ),
        sa.Column(
            "integration_health",
            sa.String(length=32),
            nullable=False,
            server_default="connected",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "bot_id", name="uq_viber_tenant_bot_id"),
    )
    op.create_index(
        "ix_connected_viber_accounts_tenant_id",
        "connected_viber_accounts",
        ["tenant_id"],
    )
    op.create_index(
        "ix_connected_viber_accounts_bot_id",
        "connected_viber_accounts",
        ["bot_id"],
    )

    op.add_column(
        "invoices",
        sa.Column("viber_connection_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_invoices_viber_connection_id",
        "invoices",
        "connected_viber_accounts",
        ["viber_connection_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_invoices_viber_connection_id", "invoices", type_="foreignkey")
    op.drop_column("invoices", "viber_connection_id")
    op.drop_index("ix_connected_viber_accounts_bot_id", "connected_viber_accounts")
    op.drop_index("ix_connected_viber_accounts_tenant_id", "connected_viber_accounts")
    op.drop_table("connected_viber_accounts")
