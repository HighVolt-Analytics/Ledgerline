"""Nullable journal invoice_id, bank_create kind, posted bank-line FK.

Revision ID: 104
Revises: 103
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "104"
down_revision: Union[str, None] = "103"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(
                sa.text(
                    "ALTER TYPE journal_entry_kind ADD VALUE IF NOT EXISTS 'bank_create'"
                )
            )

    op.alter_column(
        "journal_entries",
        "invoice_id",
        existing_type=sa.Integer(),
        nullable=True,
        existing_nullable=False,
    )

    op.add_column(
        "bank_transactions",
        sa.Column("posted_journal_batch_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_bank_transactions_posted_journal_batch_id",
        "bank_transactions",
        "journal_batches",
        ["posted_journal_batch_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_bank_transactions_posted_journal_batch_id",
        "bank_transactions",
        ["posted_journal_batch_id"],
        unique=True,
        postgresql_where=sa.text("posted_journal_batch_id IS NOT NULL"),
        sqlite_where=sa.text("posted_journal_batch_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_bank_transactions_posted_journal_batch_id",
        table_name="bank_transactions",
    )
    op.drop_constraint(
        "fk_bank_transactions_posted_journal_batch_id",
        "bank_transactions",
        type_="foreignkey",
    )
    op.drop_column("bank_transactions", "posted_journal_batch_id")
    op.alter_column(
        "journal_entries",
        "invoice_id",
        existing_type=sa.Integer(),
        nullable=False,
        existing_nullable=True,
    )
