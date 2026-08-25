"""Add contact phone to vendor masters.

Revision ID: 096
Revises: 095
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "096"
down_revision: Union[str, None] = "095"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(conn, table: str) -> bool:
    return inspect(conn).has_table(table)


def _has_column(conn, table: str, column: str) -> bool:
    return any(col["name"] == column for col in inspect(conn).get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()
    if not _has_table(conn, "vendor_masters"):
        return
    if not _has_column(conn, "vendor_masters", "contact_phone"):
        op.add_column(
            "vendor_masters",
            sa.Column("contact_phone", sa.String(length=64), nullable=False, server_default=""),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if not _has_table(conn, "vendor_masters"):
        return
    if _has_column(conn, "vendor_masters", "contact_phone"):
        op.drop_column("vendor_masters", "contact_phone")
