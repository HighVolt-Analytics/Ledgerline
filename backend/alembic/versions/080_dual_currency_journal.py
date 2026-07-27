"""Dual-currency journal lines and payment FX settlement fields.

Revision ID: 080
Revises: 079
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "080"
down_revision: Union[str, None] = "079"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(conn, table: str) -> bool:
    return inspect(conn).has_table(table)


def _has_column(conn, table: str, column: str) -> bool:
    return any(col["name"] == column for col in inspect(conn).get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()

    if _has_table(conn, "journal_entries"):
        if not _has_column(conn, "journal_entries", "txn_currency"):
            op.add_column(
                "journal_entries",
                sa.Column("txn_currency", sa.String(length=3), nullable=True),
            )
        if not _has_column(conn, "journal_entries", "base_currency"):
            op.add_column(
                "journal_entries",
                sa.Column("base_currency", sa.String(length=3), nullable=True),
            )
        if not _has_column(conn, "journal_entries", "base_debit"):
            op.add_column(
                "journal_entries",
                sa.Column("base_debit", sa.Numeric(12, 2), nullable=True),
            )
        if not _has_column(conn, "journal_entries", "base_credit"):
            op.add_column(
                "journal_entries",
                sa.Column("base_credit", sa.Numeric(12, 2), nullable=True),
            )
        if not _has_column(conn, "journal_entries", "fx_rate"):
            op.add_column(
                "journal_entries",
                sa.Column("fx_rate", sa.Numeric(18, 8), nullable=True),
            )
        if not _has_column(conn, "journal_entries", "fx_source"):
            op.add_column(
                "journal_entries",
                sa.Column("fx_source", sa.String(length=32), nullable=True),
            )

    if _has_table(conn, "payments"):
        if not _has_column(conn, "payments", "payment_fx_rate"):
            op.add_column(
                "payments",
                sa.Column("payment_fx_rate", sa.Numeric(18, 8), nullable=True),
            )
        if not _has_column(conn, "payments", "bank_payment_amount"):
            op.add_column(
                "payments",
                sa.Column("bank_payment_amount", sa.Numeric(12, 2), nullable=True),
            )
        if not _has_column(conn, "payments", "fx_variance"):
            op.add_column(
                "payments",
                sa.Column("fx_variance", sa.Numeric(12, 2), nullable=True),
            )


def downgrade() -> None:
    conn = op.get_bind()

    if _has_table(conn, "payments"):
        for col in ("fx_variance", "bank_payment_amount", "payment_fx_rate"):
            if _has_column(conn, "payments", col):
                op.drop_column("payments", col)

    if _has_table(conn, "journal_entries"):
        for col in (
            "fx_source",
            "fx_rate",
            "base_credit",
            "base_debit",
            "base_currency",
            "txn_currency",
        ):
            if _has_column(conn, "journal_entries", col):
                op.drop_column("journal_entries", col)
