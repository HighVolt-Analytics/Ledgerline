"""Team expense claim kinds and employee advance sub-ledger fields.

Revision ID: 082
Revises: 081
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "082"
down_revision: Union[str, None] = "081"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(conn, table: str) -> bool:
    return inspect(conn).has_table(table)


def _has_column(conn, table: str, column: str) -> bool:
    return any(col["name"] == column for col in inspect(conn).get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()

    if _has_table(conn, "invoices"):
        if not _has_column(conn, "invoices", "team_expense_kind"):
            op.add_column(
                "invoices",
                sa.Column("team_expense_kind", sa.String(length=32), nullable=True),
            )
        if not _has_column(conn, "invoices", "linked_advance_invoice_id"):
            op.add_column(
                "invoices",
                sa.Column("linked_advance_invoice_id", sa.Integer(), nullable=True),
            )

    if _has_table(conn, "employee_masters"):
        if not _has_column(conn, "employee_masters", "advance_parent_ledger"):
            op.add_column(
                "employee_masters",
                sa.Column(
                    "advance_parent_ledger",
                    sa.String(length=255),
                    nullable=False,
                    server_default="",
                ),
            )
        if not _has_column(conn, "employee_masters", "advance_sub_ledger"):
            op.add_column(
                "employee_masters",
                sa.Column(
                    "advance_sub_ledger",
                    sa.String(length=255),
                    nullable=False,
                    server_default="",
                ),
            )


def downgrade() -> None:
    conn = op.get_bind()

    if _has_table(conn, "employee_masters"):
        for col in ("advance_sub_ledger", "advance_parent_ledger"):
            if _has_column(conn, "employee_masters", col):
                op.drop_column("employee_masters", col)

    if _has_table(conn, "invoices"):
        for col in ("linked_advance_invoice_id", "team_expense_kind"):
            if _has_column(conn, "invoices", col):
                op.drop_column("invoices", col)
