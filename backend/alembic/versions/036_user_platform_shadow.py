"""Add is_platform_shadow flag on users for super-admin support access.

Revision ID: 036
Revises: 035
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "036"
down_revision: Union[str, None] = "035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("users")}
    if "is_platform_shadow" not in columns:
        op.add_column(
            "users",
            sa.Column("is_platform_shadow", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    # Backfill: client-tenant users whose auth account matches a platform super_admin.
    op.execute(
        sa.text(
            """
            UPDATE users AS u
            SET is_platform_shadow = TRUE
            FROM tenants AS client_t
            JOIN tenants AS platform_t ON platform_t.is_platform = TRUE
            JOIN users AS platform_u ON platform_u.tenant_id = platform_t.id
            WHERE u.tenant_id = client_t.id
              AND client_t.is_platform = FALSE
              AND platform_u.role = 'super_admin'
              AND u.auth_account_id IS NOT NULL
              AND u.auth_account_id = platform_u.auth_account_id
            """
        )
    )


def downgrade() -> None:
    op.drop_column("users", "is_platform_shadow")
