"""Payment execution instructions for manual orchestration.

Revision ID: 041
Revises: 040
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "041"
down_revision: Union[str, None] = "040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_execution_instructions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Integer(), nullable=False),
        sa.Column("instruction_reference", sa.String(length=64), nullable=False),
        sa.Column("execution_mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("vendor_name", sa.String(length=255), nullable=True),
        sa.Column("vendor_payout_method_label", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_by_name", sa.String(length=255), nullable=True),
        sa.Column("created_by_email", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id", name="uq_payment_execution_instructions_payment_id"),
    )
    op.create_index(
        "ix_payment_execution_instructions_tenant_id",
        "payment_execution_instructions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_payment_execution_instructions_payment_id",
        "payment_execution_instructions",
        ["payment_id"],
    )
    op.create_index(
        "ix_payment_execution_instructions_instruction_reference",
        "payment_execution_instructions",
        ["instruction_reference"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payment_execution_instructions_instruction_reference",
        table_name="payment_execution_instructions",
    )
    op.drop_index(
        "ix_payment_execution_instructions_payment_id",
        table_name="payment_execution_instructions",
    )
    op.drop_index(
        "ix_payment_execution_instructions_tenant_id",
        table_name="payment_execution_instructions",
    )
    op.drop_table("payment_execution_instructions")
