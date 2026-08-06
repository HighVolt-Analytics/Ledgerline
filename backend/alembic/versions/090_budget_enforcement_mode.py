"""GL budgets: soft vs hard overrun enforcement.

Revision ID: 090
Revises: 089
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "090"
down_revision: Union[str, None] = "089"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(conn, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspect(conn).get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()
    if not inspect(conn).has_table("department_budgets"):
        return
    if _has_column(conn, "department_budgets", "enforcement"):
        return
    op.add_column(
        "department_budgets",
        sa.Column(
            "enforcement",
            sa.String(16),
            nullable=False,
            server_default="soft",
        ),
    )


def downgrade() -> None:
    conn = op.get_bind()
    if not inspect(conn).has_table("department_budgets"):
        return
    if not _has_column(conn, "department_budgets", "enforcement"):
        return
    op.drop_column("department_budgets", "enforcement")
