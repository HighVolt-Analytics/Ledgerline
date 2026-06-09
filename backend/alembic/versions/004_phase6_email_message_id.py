"""phase6: link invoices to Graph message id

Revision ID: 004
Revises: 003
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("email_message_id", sa.String(255), nullable=True),
    )
    op.create_index("ix_invoices_email_message_id", "invoices", ["email_message_id"])


def downgrade() -> None:
    op.drop_index("ix_invoices_email_message_id", table_name="invoices")
    op.drop_column("invoices", "email_message_id")
