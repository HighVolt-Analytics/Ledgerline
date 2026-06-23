"""Normalize tenant membership role slugs."""

from typing import Sequence, Union

from alembic import op

revision: str = "030"
down_revision: Union[str, None] = "029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE user_tenant_mappings
        SET role = 'approver'
        WHERE role IS NULL OR role = '' OR role = 'member'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE user_tenant_mappings
        SET role = 'member'
        WHERE role = 'approver'
        """
    )
