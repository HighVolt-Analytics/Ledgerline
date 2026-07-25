"""Widen line_items.unit_price to NUMERIC(12,4) for sub-cent unit prices.

Revision ID: 079
Revises: 078
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "079"
down_revision: Union[str, None] = "078"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(conn, table: str) -> bool:
    return inspect(conn).has_table(table)


def upgrade() -> None:
    conn = op.get_bind()
    if not _has_table(conn, "line_items"):
        return
    op.alter_column(
        "line_items",
        "unit_price",
        existing_type=sa.Numeric(12, 2),
        type_=sa.Numeric(12, 4),
        existing_nullable=True,
    )


def downgrade() -> None:
    conn = op.get_bind()
    if not _has_table(conn, "line_items"):
        return
    op.alter_column(
        "line_items",
        "unit_price",
        existing_type=sa.Numeric(12, 4),
        type_=sa.Numeric(12, 2),
        existing_nullable=True,
    )
