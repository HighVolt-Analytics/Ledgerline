"""Add extraction provenance columns to line_items.

Revision ID: 066
Revises: 065
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "066"
down_revision: Union[str, None] = "065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("line_items", sa.Column("extraction_source", sa.String(length=32), nullable=True))
    op.add_column("line_items", sa.Column("source_confidence", sa.Numeric(5, 4), nullable=True))
    op.add_column("line_items", sa.Column("fused_from", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("line_items", "fused_from")
    op.drop_column("line_items", "source_confidence")
    op.drop_column("line_items", "extraction_source")
