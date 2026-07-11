"""Add hosted invoice / receipt URLs to credit ledger entries.

Revision ID: 067
Revises: 066
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "067"
down_revision: Union[str, None] = "066"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "credit_ledger_entries",
        sa.Column("stripe_hosted_invoice_url", sa.String(length=2048), nullable=True),
    )
    op.add_column(
        "credit_ledger_entries",
        sa.Column("stripe_receipt_url", sa.String(length=2048), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("credit_ledger_entries", "stripe_receipt_url")
    op.drop_column("credit_ledger_entries", "stripe_hosted_invoice_url")
