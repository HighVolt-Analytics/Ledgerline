"""Add extraction provenance columns to line_items.

Revision ID: 066
Revises: 065
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "066"
down_revision: Union[str, None] = "065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(conn, table: str, column: str) -> bool:
    if not inspect(conn).has_table(table):
        return False
    return column in {c["name"] for c in inspect(conn).get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    if not _has_column(conn, "line_items", "extraction_source"):
        op.add_column("line_items", sa.Column("extraction_source", sa.String(length=32), nullable=True))
    if not _has_column(conn, "line_items", "source_confidence"):
        op.add_column("line_items", sa.Column("source_confidence", sa.Numeric(5, 4), nullable=True))
    if not _has_column(conn, "line_items", "fused_from"):
        op.add_column("line_items", sa.Column("fused_from", sa.JSON(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    if _has_column(conn, "line_items", "fused_from"):
        op.drop_column("line_items", "fused_from")
    if _has_column(conn, "line_items", "source_confidence"):
        op.drop_column("line_items", "source_confidence")
    if _has_column(conn, "line_items", "extraction_source"):
        op.drop_column("line_items", "extraction_source")
