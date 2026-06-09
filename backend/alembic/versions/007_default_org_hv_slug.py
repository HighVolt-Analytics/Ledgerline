"""Rename legacy default org slug to hv-org for vault folder layout.

Revision ID: 007
Revises: 006
"""

from typing import Sequence, Union

from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE organisations
        SET slug = 'hv-org'
        WHERE slug = 'default'
          AND NOT EXISTS (
            SELECT 1 FROM organisations AS o2 WHERE o2.slug = 'hv-org'
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE organisations
        SET slug = 'default'
        WHERE slug = 'hv-org'
          AND NOT EXISTS (
            SELECT 1 FROM organisations AS o2 WHERE o2.slug = 'default'
          )
        """
    )
