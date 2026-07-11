"""Add hosted invoice / receipt URLs to credit ledger entries.

Revision ID: 067
Revises: 066
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "067"
down_revision: Union[str, None] = "066"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(conn, table: str, column: str) -> bool:
    if not inspect(conn).has_table(table):
        return False
    return column in {c["name"] for c in inspect(conn).get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    if not _has_column(conn, "credit_ledger_entries", "stripe_hosted_invoice_url"):
        op.add_column(
            "credit_ledger_entries",
            sa.Column("stripe_hosted_invoice_url", sa.String(length=2048), nullable=True),
        )
    if not _has_column(conn, "credit_ledger_entries", "stripe_receipt_url"):
        op.add_column(
            "credit_ledger_entries",
            sa.Column("stripe_receipt_url", sa.String(length=2048), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _has_column(conn, "credit_ledger_entries", "stripe_receipt_url"):
        op.drop_column("credit_ledger_entries", "stripe_receipt_url")
    if _has_column(conn, "credit_ledger_entries", "stripe_hosted_invoice_url"):
        op.drop_column("credit_ledger_entries", "stripe_hosted_invoice_url")
