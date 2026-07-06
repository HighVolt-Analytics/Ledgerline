"""Pending customer registration queue.

Revision ID: 060
Revises: 059
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "060"
down_revision: Union[str, None] = "059"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_customers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("detected_name", sa.String(255), nullable=False),
        sa.Column("detected_abn", sa.String(11)),
        sa.Column("detected_address", sa.String(500)),
        sa.Column("source_invoice_id", sa.Integer()),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("promoted_master_id", sa.String(100)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["source_invoice_id"], ["invoices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pending_customers_tenant_id", "pending_customers", ["tenant_id"])
    op.create_index("ix_pending_customers_status", "pending_customers", ["status"])


def downgrade() -> None:
    op.drop_index("ix_pending_customers_status", table_name="pending_customers")
    op.drop_index("ix_pending_customers_tenant_id", table_name="pending_customers")
    op.drop_table("pending_customers")
