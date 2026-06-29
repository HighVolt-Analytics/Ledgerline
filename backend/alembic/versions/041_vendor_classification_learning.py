"""Per-vendor classification learning key on learning events.

Revision ID: 046
Revises: 045
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "046"
down_revision: Union[str, None] = "045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "classification_learning_events",
        sa.Column("vendor_key", sa.String(length=100), nullable=True),
    )
    op.create_index(
        "ix_classification_learning_events_vendor_key",
        "classification_learning_events",
        ["vendor_key"],
    )
    op.create_index(
        "ix_classification_learning_events_tenant_vendor",
        "classification_learning_events",
        ["tenant_id", "vendor_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_classification_learning_events_tenant_vendor",
        table_name="classification_learning_events",
    )
    op.drop_index(
        "ix_classification_learning_events_vendor_key",
        table_name="classification_learning_events",
    )
    op.drop_column("classification_learning_events", "vendor_key")
