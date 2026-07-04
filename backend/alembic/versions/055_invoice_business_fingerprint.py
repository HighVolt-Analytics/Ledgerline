"""Add business_fingerprint for catalogue-driven duplicate detection.

Revision ID: 055
Revises: 054
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "055"
down_revision: Union[str, None] = "054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("business_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_invoices_business_fingerprint",
        "invoices",
        ["business_fingerprint"],
        unique=False,
    )
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute(
            """
            CREATE UNIQUE INDEX uq_invoice_tenant_business_fingerprint
            ON invoices (tenant_id, business_fingerprint)
            WHERE business_fingerprint IS NOT NULL
            """
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS uq_invoice_tenant_business_fingerprint")
    op.drop_index("ix_invoices_business_fingerprint", table_name="invoices")
    op.drop_column("invoices", "business_fingerprint")
