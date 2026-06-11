"""Add three_way_match_status to purchase_orders.

Revision ID: 017
Revises: 016
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017"
down_revision: Union[str, None] = "016_purchase_documents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "purchase_orders",
        sa.Column("three_way_match_status", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_purchase_orders_three_way_match_status",
        "purchase_orders",
        ["three_way_match_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_purchase_orders_three_way_match_status", table_name="purchase_orders")
    op.drop_column("purchase_orders", "three_way_match_status")
