"""Persist document heading and custom extracted fields on invoices.

Revision ID: 045
Revises: 044
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "045"
down_revision: Union[str, None] = "044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JsonColumn = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column("invoices", sa.Column("document_heading", sa.String(500), nullable=True))
    op.add_column("invoices", sa.Column("extracted_fields", _JsonColumn, nullable=True))


def downgrade() -> None:
    op.drop_column("invoices", "extracted_fields")
    op.drop_column("invoices", "document_heading")
