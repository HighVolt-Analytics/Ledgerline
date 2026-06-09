"""phase2 vendor registry and invoice email metadata

Revision ID: 002
Revises: 001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("email_sender", sa.String(255)))
    op.add_column("invoices", sa.Column("storage_vendor_slug", sa.String(100)))

    op.create_table(
        "vendor_registry",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("vendor_slug", sa.String(100), nullable=False),
        sa.Column("vendor_name", sa.String(255), nullable=False),
        sa.Column("sender_pattern", sa.String(255), nullable=False),
        sa.Column("abn", sa.String(11)),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("vendor_slug"),
    )
    op.create_index("ix_vendor_registry_sender_pattern", "vendor_registry", ["sender_pattern"])


def downgrade() -> None:
    op.drop_index("ix_vendor_registry_sender_pattern", table_name="vendor_registry")
    op.drop_table("vendor_registry")
    op.drop_column("invoices", "storage_vendor_slug")
    op.drop_column("invoices", "email_sender")
