"""Payment batch bank-file export tracking (e.g. AU ABA batch exports).

Revision ID: 106
Revises: 105
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "106"
down_revision: Union[str, None] = "105"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("bank_file_batch_reference", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("bank_file_exported_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_payments_bank_file_batch_reference",
        "payments",
        ["bank_file_batch_reference"],
    )


def downgrade() -> None:
    op.drop_index("ix_payments_bank_file_batch_reference", table_name="payments")
    op.drop_column("payments", "bank_file_exported_at")
    op.drop_column("payments", "bank_file_batch_reference")
