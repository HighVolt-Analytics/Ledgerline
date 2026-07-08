"""Add signup_source to pending signup billing sessions.

Revision ID: 062
Revises: 061
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "062"
down_revision: Union[str, None] = "061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pending_signup_billing_sessions",
        sa.Column("signup_source", sa.String(length=20), server_default="public", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("pending_signup_billing_sessions", "signup_source")
