"""Bank transfer journal kind + transaction notes for Discuss tab.

Revision ID: 105
Revises: 104
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "105"
down_revision: Union[str, None] = "104"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(
                sa.text(
                    "ALTER TYPE journal_entry_kind ADD VALUE IF NOT EXISTS 'bank_transfer'"
                )
            )

    op.create_table(
        "bank_transaction_notes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("bank_transaction_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["author_user_id"], ["auth_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["bank_transaction_id"], ["bank_transactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bank_transaction_notes_tenant_txn",
        "bank_transaction_notes",
        ["tenant_id", "bank_transaction_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_bank_transaction_notes_tenant_txn", table_name="bank_transaction_notes")
    op.drop_table("bank_transaction_notes")
