"""Add document_text to invoices for config-driven classification.

Revision ID: 023
Revises: 022
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("document_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("invoices", "document_text")
