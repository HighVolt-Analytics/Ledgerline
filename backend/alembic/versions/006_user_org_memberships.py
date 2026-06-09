"""user_org_memberships for demo multi-org switching

Revision ID: 006
Revises: 005
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_org_memberships",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "org_id", name="uq_user_org"),
    )
    op.create_index("ix_user_org_memberships_user_id", "user_org_memberships", ["user_id"])
    op.create_index("ix_user_org_memberships_org_id", "user_org_memberships", ["org_id"])

    op.execute(
        """
        INSERT INTO user_org_memberships (user_id, org_id)
        SELECT id, org_id FROM users
        ON CONFLICT (user_id, org_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_user_org_memberships_org_id", table_name="user_org_memberships")
    op.drop_index("ix_user_org_memberships_user_id", table_name="user_org_memberships")
    op.drop_table("user_org_memberships")
