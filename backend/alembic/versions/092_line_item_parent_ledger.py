"""Store per-line parent (main) GL so clerks can override document-type Post To.

Revision ID: 092
Revises: 091
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "092"
down_revision: Union[str, None] = "091"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("line_items", sa.Column("parent_ledger", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("line_items", "parent_ledger")
