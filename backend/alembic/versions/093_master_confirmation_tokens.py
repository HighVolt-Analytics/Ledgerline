"""Master data confirmation tokens and vendor contact email.

Revision ID: 093
Revises: 092
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "093"
down_revision: Union[str, None] = "092"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vendor_masters",
        sa.Column("contact_email", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "vendor_masters",
        sa.Column("confirmation_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "vendor_masters",
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "employee_masters",
        sa.Column("confirmation_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "employee_masters",
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "master_confirmation_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("master_id", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_master_confirmation_tokens_tenant_kind_master",
        "master_confirmation_tokens",
        ["tenant_id", "kind", "master_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_master_confirmation_tokens_tenant_kind_master", table_name="master_confirmation_tokens")
    op.drop_table("master_confirmation_tokens")
    op.drop_column("employee_masters", "confirmed_at")
    op.drop_column("employee_masters", "confirmation_sent_at")
    op.drop_column("vendor_masters", "confirmed_at")
    op.drop_column("vendor_masters", "confirmation_sent_at")
    op.drop_column("vendor_masters", "contact_email")
