"""Unset shadow flag on real tenant owners incorrectly flagged by 036.

Revision ID: 037
Revises: 036
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "037"
down_revision: Union[str, None] = "036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE users AS u
            SET is_platform_shadow = FALSE
            FROM (
                SELECT tenant_id, MIN(id) AS first_user_id
                FROM users
                WHERE tenant_id IN (
                    SELECT id FROM tenants WHERE is_platform = FALSE
                )
                GROUP BY tenant_id
            ) AS first_per_tenant
            WHERE u.id = first_per_tenant.first_user_id
              AND u.is_platform_shadow = TRUE
            """
        )
    )


def downgrade() -> None:
    pass
