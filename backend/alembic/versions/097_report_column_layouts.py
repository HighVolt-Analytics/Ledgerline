"""Per-user named report column layouts.

Revision ID: 097
Revises: 096
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "097"
down_revision: Union[str, None] = "096"
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
    json_type = sa.JSON().with_variant(JSONB, "postgresql")
    op.create_table(
        "report_column_layouts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("column_config", json_type, nullable=False),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
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
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "report_id",
            "name",
            name="uq_report_column_layout_name",
        ),
    )
    op.create_index(
        "ix_report_column_layouts_tenant_id",
        "report_column_layouts",
        ["tenant_id"],
    )
    op.create_index(
        "ix_report_column_layouts_user_id",
        "report_column_layouts",
        ["user_id"],
    )
    op.create_index(
        "uq_report_column_layout_default",
        "report_column_layouts",
        ["tenant_id", "user_id", "report_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
        sqlite_where=sa.text("is_default = 1"),
    )

    conn = op.get_bind()
    _enable_rls(conn, "report_column_layouts")


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(
            sa.text('DROP POLICY IF EXISTS tenant_isolation ON "report_column_layouts"')
        )
        conn.execute(
            sa.text(
                'ALTER TABLE "report_column_layouts" NO FORCE ROW LEVEL SECURITY'
            )
        )
        conn.execute(
            sa.text('ALTER TABLE "report_column_layouts" DISABLE ROW LEVEL SECURITY')
        )
    op.drop_index(
        "uq_report_column_layout_default", table_name="report_column_layouts"
    )
    op.drop_index(
        "ix_report_column_layouts_user_id", table_name="report_column_layouts"
    )
    op.drop_index(
        "ix_report_column_layouts_tenant_id", table_name="report_column_layouts"
    )
    op.drop_table("report_column_layouts")
