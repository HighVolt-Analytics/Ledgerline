"""Vendor payout method readiness fields.

Revision ID: 039
Revises: 038
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "039"
down_revision: Union[str, None] = "038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vendor_payment_methods",
        sa.Column("display_label", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "vendor_payment_methods",
        sa.Column("currency", sa.String(length=3), server_default="AUD", nullable=False),
    )
    op.add_column(
        "vendor_payment_methods",
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.alter_column(
        "vendor_payment_methods",
        "external_account_last4",
        new_column_name="last4",
        existing_type=sa.String(length=4),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "vendor_payment_methods",
        "last4",
        new_column_name="external_account_last4",
        existing_type=sa.String(length=4),
        existing_nullable=True,
    )
    op.drop_column("vendor_payment_methods", "is_default")
    op.drop_column("vendor_payment_methods", "currency")
    op.drop_column("vendor_payment_methods", "display_label")
