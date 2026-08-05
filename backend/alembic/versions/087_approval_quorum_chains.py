"""Add approval_chain JSON for multi-approver quorum.

Revision ID: 087
Revises: 086
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "087"
down_revision: Union[str, None] = "086"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(conn, table: str, column: str) -> bool:
    insp = inspect(conn)
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

    if not _has_column(conn, "invoices", "approval_chain"):
        op.add_column("invoices", sa.Column("approval_chain", json_type, nullable=True))
    if not _has_column(conn, "purchase_orders", "variance_approval_chain"):
        op.add_column(
            "purchase_orders",
            sa.Column("variance_approval_chain", json_type, nullable=True),
        )
    if not _has_column(conn, "sales_orders", "variance_approval_chain"):
        op.add_column(
            "sales_orders",
            sa.Column("variance_approval_chain", json_type, nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _has_column(conn, "sales_orders", "variance_approval_chain"):
        op.drop_column("sales_orders", "variance_approval_chain")
    if _has_column(conn, "purchase_orders", "variance_approval_chain"):
        op.drop_column("purchase_orders", "variance_approval_chain")
    if _has_column(conn, "invoices", "approval_chain"):
        op.drop_column("invoices", "approval_chain")
