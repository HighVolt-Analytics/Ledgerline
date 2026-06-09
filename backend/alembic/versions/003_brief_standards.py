"""brief standards: po_reference, cost_centre, line tax_amount

Revision ID: 003
Revises: 002
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("po_reference", sa.String(100), nullable=True))
    op.add_column("invoices", sa.Column("cost_centre", sa.String(100), nullable=True))
    op.add_column("line_items", sa.Column("tax_amount", sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("line_items", "tax_amount")
    op.drop_column("invoices", "cost_centre")
    op.drop_column("invoices", "po_reference")
