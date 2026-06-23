"""Tenant member invite tokens."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "031"
down_revision: Union[str, None] = "030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_member_invites",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("invited_by_user_id", sa.Integer(), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_tenant_member_invites_tenant_id",
        "tenant_member_invites",
        ["tenant_id"],
    )
    op.create_index(
        "ix_tenant_member_invites_email",
        "tenant_member_invites",
        ["email"],
    )
    op.create_index(
        "ix_tenant_member_invites_token_hash",
        "tenant_member_invites",
        ["token_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_member_invites_token_hash", table_name="tenant_member_invites")
    op.drop_index("ix_tenant_member_invites_email", table_name="tenant_member_invites")
    op.drop_index("ix_tenant_member_invites_tenant_id", table_name="tenant_member_invites")
    op.drop_table("tenant_member_invites")
