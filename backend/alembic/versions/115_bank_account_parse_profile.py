"""Add statement_parse_profile_id to bank_accounts.

Revision ID: 115
Revises: 114
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "115"
down_revision: Union[str, None] = "114"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bank_accounts",
        sa.Column("statement_parse_profile_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bank_accounts", "statement_parse_profile_id")
