"""Persist manual uploader identity on invoices.

Revision ID: 073
Revises: 072
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "073"
down_revision: Union[str, None] = "072"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("uploaded_by_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("uploaded_by_email", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invoices", "uploaded_by_email")
    op.drop_column("invoices", "uploaded_by_name")
