"""Add organisation fields to employee masters.

Revision ID: 083
Revises: 082
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "083"
down_revision: Union[str, None] = "082"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS: tuple[tuple[str, int], ...] = (
    ("whatsapp_number_2", 32),
    ("date_of_joining", 32),
    ("department", 255),
    ("location", 255),
    ("division", 255),
    ("supervisor_1", 255),
    ("supervisor_2", 255),
)


def _has_table(conn, table: str) -> bool:
    return inspect(conn).has_table(table)


def _has_column(conn, table: str, column: str) -> bool:
    return any(col["name"] == column for col in inspect(conn).get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()
    if not _has_table(conn, "employee_masters"):
        return
    for name, length in _COLUMNS:
        if not _has_column(conn, "employee_masters", name):
            op.add_column(
                "employee_masters",
                sa.Column(name, sa.String(length=length), nullable=False, server_default=""),
            )


def downgrade() -> None:
    conn = op.get_bind()
    if not _has_table(conn, "employee_masters"):
        return
    for name, _length in _COLUMNS:
        if _has_column(conn, "employee_masters", name):
            op.drop_column("employee_masters", name)
