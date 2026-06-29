"""UOM fields for three-way quantity match.

Revision ID: 047
Revises: 046
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "047"
down_revision: Union[str, None] = "046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("line_items", sa.Column("uom", sa.String(length=32), nullable=True))
    op.add_column("line_items", sa.Column("sku", sa.String(length=100), nullable=True))
    op.add_column("purchase_orders", sa.Column("po_uom", sa.String(length=32), nullable=True))
    op.add_column("goods_receipts", sa.Column("grn_uom", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("goods_receipts", "grn_uom")
    op.drop_column("purchase_orders", "po_uom")
    op.drop_column("line_items", "sku")
    op.drop_column("line_items", "uom")
