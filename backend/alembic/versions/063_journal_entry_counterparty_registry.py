"""Add vendor/customer registry identity to journal entries.

Revision ID: 063
Revises: 062
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "063"
down_revision: Union[str, None] = "062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "journal_entries",
        sa.Column("vendor_registry_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "journal_entries",
        sa.Column("customer_registry_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_journal_entries_vendor_registry_id",
        "journal_entries",
        "vendor_registry",
        ["vendor_registry_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_journal_entries_customer_registry_id",
        "journal_entries",
        "customer_registry",
        ["customer_registry_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_journal_entries_vendor_registry_id",
        "journal_entries",
        ["vendor_registry_id"],
    )
    op.create_index(
        "ix_journal_entries_customer_registry_id",
        "journal_entries",
        ["customer_registry_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_journal_entries_customer_registry_id", table_name="journal_entries")
    op.drop_index("ix_journal_entries_vendor_registry_id", table_name="journal_entries")
    op.drop_constraint(
        "fk_journal_entries_customer_registry_id",
        "journal_entries",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_journal_entries_vendor_registry_id",
        "journal_entries",
        type_="foreignkey",
    )
    op.drop_column("journal_entries", "customer_registry_id")
    op.drop_column("journal_entries", "vendor_registry_id")
