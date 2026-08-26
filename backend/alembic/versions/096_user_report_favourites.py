"""Per-user report catalogue favourites.

Revision ID: 096
Revises: 095
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "096"
down_revision: Union[str, None] = "095"
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
        "user_report_favourites",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "user_id", "report_id", name="uq_user_report_favourite"
        ),
    )
    op.create_index(
        "ix_user_report_favourites_tenant_id",
        "user_report_favourites",
        ["tenant_id"],
    )
    op.create_index(
        "ix_user_report_favourites_user_id",
        "user_report_favourites",
        ["user_id"],
    )

    conn = op.get_bind()
    _enable_rls(conn, "user_report_favourites")


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(
            sa.text('DROP POLICY IF EXISTS tenant_isolation ON "user_report_favourites"')
        )
        conn.execute(
            sa.text(
                'ALTER TABLE "user_report_favourites" NO FORCE ROW LEVEL SECURITY'
            )
        )
        conn.execute(
            sa.text('ALTER TABLE "user_report_favourites" DISABLE ROW LEVEL SECURITY')
        )
    op.drop_index(
        "ix_user_report_favourites_user_id", table_name="user_report_favourites"
    )
    op.drop_index(
        "ix_user_report_favourites_tenant_id", table_name="user_report_favourites"
    )
    op.drop_table("user_report_favourites")
