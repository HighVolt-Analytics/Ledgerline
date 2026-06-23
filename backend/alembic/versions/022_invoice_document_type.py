"""Add document_type_code and document_type_confidence to invoices.

Revision ID: 022
Revises: 021
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("document_type_code", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("document_type_confidence", sa.Float(), nullable=True),
    )
    op.create_index(
        "ix_invoices_document_type_code",
        "invoices",
        ["document_type_code"],
    )


def downgrade() -> None:
    op.drop_index("ix_invoices_document_type_code", table_name="invoices")
    op.drop_column("invoices", "document_type_confidence")
    op.drop_column("invoices", "document_type_code")
