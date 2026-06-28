"""Add proof reference for manual paid confirmation.

Revision ID: 042
Revises: 041
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "042"
down_revision: Union[str, None] = "041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_execution_instructions",
        sa.Column("proof_reference", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "payment_execution_instructions",
        sa.Column("marked_paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "payment_execution_instructions",
        sa.Column("marked_paid_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_payment_execution_instructions_marked_paid_by_user_id",
        "payment_execution_instructions",
        "users",
        ["marked_paid_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_payment_execution_instructions_marked_paid_by_user_id",
        "payment_execution_instructions",
        type_="foreignkey",
    )
    op.drop_column("payment_execution_instructions", "marked_paid_by_user_id")
    op.drop_column("payment_execution_instructions", "marked_paid_at")
    op.drop_column("payment_execution_instructions", "proof_reference")
