"""FX booking and payment variance fields.

Revision ID: 048
Revises: 047
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "048"
down_revision: Union[str, None] = "047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("booking_fx_rate", sa.Numeric(12, 6), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("functional_currency", sa.String(length=3), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("functional_total", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "purchase_orders",
        sa.Column("po_currency", sa.String(length=3), nullable=True),
    )
    op.add_column(
        "goods_receipts",
        sa.Column("grn_currency", sa.String(length=3), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("payment_fx_rate", sa.Numeric(12, 6), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("bank_payment_amount", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("fx_variance", sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payments", "fx_variance")
    op.drop_column("payments", "bank_payment_amount")
    op.drop_column("payments", "payment_fx_rate")
    op.drop_column("goods_receipts", "grn_currency")
    op.drop_column("purchase_orders", "po_currency")
    op.drop_column("invoices", "functional_total")
    op.drop_column("invoices", "functional_currency")
    op.drop_column("invoices", "booking_fx_rate")
