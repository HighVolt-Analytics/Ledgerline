"""Add user_notification_cursors for bell inbox read state.

Revision ID: 057
Revises: 056
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "057"
down_revision: Union[str, None] = "056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _enable_rls(conn, table: str) -> None:
    if conn.dialect.name != "postgresql":
        return
    conn.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
    conn.execute(sa.text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
    conn.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = 'public'
                  AND tablename = '{table}'
                  AND policyname = 'tenant_isolation'
              ) THEN
                CREATE POLICY tenant_isolation ON "{table}"
                  USING (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  )
                  WITH CHECK (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  );
              END IF;
            END $$;
            """
        )
    )


def upgrade() -> None:
    op.create_table(
        "user_notification_cursors",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "last_read_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_user_notification_cursor"),
    )
    op.create_index(
        "ix_user_notification_cursors_tenant_id",
        "user_notification_cursors",
        ["tenant_id"],
    )

    conn = op.get_bind()
    _enable_rls(conn, "user_notification_cursors")


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(
            sa.text(
                'DROP POLICY IF EXISTS tenant_isolation ON "user_notification_cursors"'
            )
        )
        conn.execute(
            sa.text('ALTER TABLE "user_notification_cursors" NO FORCE ROW LEVEL SECURITY')
        )
        conn.execute(
            sa.text('ALTER TABLE "user_notification_cursors" DISABLE ROW LEVEL SECURITY')
        )
    op.drop_index("ix_user_notification_cursors_tenant_id", table_name="user_notification_cursors")
    op.drop_table("user_notification_cursors")
