"""Add line-item sub-ledger and GL mapping metadata.

Revision ID: 059
Revises: 058
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "059"
down_revision: Union[str, None] = "058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("line_items", sa.Column("sub_ledger", sa.String(length=128), nullable=True))
    op.add_column("line_items", sa.Column("gl_mapping_source", sa.String(length=32), nullable=True))
    op.add_column(
        "line_items",
        sa.Column("gl_mapping_confidence", sa.Numeric(5, 4), nullable=True),
    )
    op.add_column("line_items", sa.Column("gl_mapping_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("line_items", "gl_mapping_reason")
    op.drop_column("line_items", "gl_mapping_confidence")
    op.drop_column("line_items", "gl_mapping_source")
    op.drop_column("line_items", "sub_ledger")
