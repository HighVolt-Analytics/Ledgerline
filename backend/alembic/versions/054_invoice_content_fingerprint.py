"""Add content_fingerprint for cross-format PDF duplicate detection.

Revision ID: 054
Revises: 053
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "054"
down_revision: Union[str, None] = "053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("content_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_invoices_content_fingerprint",
        "invoices",
        ["content_fingerprint"],
        unique=False,
    )
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute(
            """
            CREATE UNIQUE INDEX uq_invoice_tenant_content_fingerprint
            ON invoices (tenant_id, content_fingerprint)
            WHERE content_fingerprint IS NOT NULL
            """
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS uq_invoice_tenant_content_fingerprint")
    op.drop_index("ix_invoices_content_fingerprint", table_name="invoices")
    op.drop_column("invoices", "content_fingerprint")
