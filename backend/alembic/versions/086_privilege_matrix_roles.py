"""Expand tenant privilege-matrix roles.

Maps legacy membership/invite slugs:
  approver → functional_manager
  viewer → user

Revision ID: 086
Revises: 085
"""

from typing import Sequence, Union

from alembic import op

revision: str = "086"
down_revision: Union[str, None] = "085"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE user_tenant_mappings
        SET role = 'functional_manager'
        WHERE role = 'approver'
        """
    )
    op.execute(
        """
        UPDATE user_tenant_mappings
        SET role = 'user'
        WHERE role = 'viewer'
        """
    )
    op.execute(
        """
        UPDATE tenant_member_invites
        SET role = 'functional_manager'
        WHERE role = 'approver'
        """
    )
    op.execute(
        """
        UPDATE tenant_member_invites
        SET role = 'user'
        WHERE role = 'viewer'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE user_tenant_mappings
        SET role = 'approver'
        WHERE role = 'functional_manager'
        """
    )
    op.execute(
        """
        UPDATE user_tenant_mappings
        SET role = 'viewer'
        WHERE role = 'user'
        """
    )
    op.execute(
        """
        UPDATE tenant_member_invites
        SET role = 'approver'
        WHERE role = 'functional_manager'
        """
    )
    op.execute(
        """
        UPDATE tenant_member_invites
        SET role = 'viewer'
        WHERE role = 'user'
        """
    )
