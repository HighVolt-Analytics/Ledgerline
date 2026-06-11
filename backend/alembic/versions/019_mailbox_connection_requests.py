"""Mailbox connection invite requests.

Revision ID: 019
Revises: 018
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mailbox_connection_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("requested_email", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("connected_mailbox_id", sa.Integer(), nullable=True),
        sa.Column("invite_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["connected_mailbox_id"], ["connected_mailboxes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mailbox_connection_requests_org_id",
        "mailbox_connection_requests",
        ["org_id"],
    )
    op.create_index(
        "ix_mailbox_connection_requests_requested_email",
        "mailbox_connection_requests",
        ["requested_email"],
    )
    op.create_index(
        "ix_mailbox_connection_requests_status",
        "mailbox_connection_requests",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_mailbox_connection_requests_status", table_name="mailbox_connection_requests")
    op.drop_index(
        "ix_mailbox_connection_requests_requested_email",
        table_name="mailbox_connection_requests",
    )
    op.drop_index("ix_mailbox_connection_requests_org_id", table_name="mailbox_connection_requests")
    op.drop_table("mailbox_connection_requests")
