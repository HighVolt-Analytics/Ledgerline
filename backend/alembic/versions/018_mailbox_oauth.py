"""OAuth delegated tokens for connected mailboxes.

Revision ID: 018
Revises: 017
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "connected_mailboxes",
        sa.Column("auth_type", sa.String(length=32), nullable=False, server_default="application"),
    )
    op.add_column(
        "connected_mailboxes",
        sa.Column("connection_status", sa.String(length=32), nullable=False, server_default="connected"),
    )
    op.add_column(
        "connected_mailboxes",
        sa.Column("oauth_user_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "connected_mailboxes",
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "connected_mailboxes",
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "connected_mailboxes",
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "connected_mailboxes",
        sa.Column("oauth_connected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "connected_mailboxes",
        sa.Column("last_error", sa.String(length=512), nullable=True),
    )
    op.create_index(
        "ix_connected_mailboxes_connection_status",
        "connected_mailboxes",
        ["connection_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_connected_mailboxes_connection_status", table_name="connected_mailboxes")
    op.drop_column("connected_mailboxes", "last_error")
    op.drop_column("connected_mailboxes", "oauth_connected_at")
    op.drop_column("connected_mailboxes", "token_expires_at")
    op.drop_column("connected_mailboxes", "refresh_token_encrypted")
    op.drop_column("connected_mailboxes", "access_token_encrypted")
    op.drop_column("connected_mailboxes", "oauth_user_id")
    op.drop_column("connected_mailboxes", "connection_status")
    op.drop_column("connected_mailboxes", "auth_type")
