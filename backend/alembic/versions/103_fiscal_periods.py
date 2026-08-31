"""Add fiscal_periods table for period-close locking.

No row for a date = open. This is a non-breaking rollout: every existing
tenant stays fully open on every date until they explicitly close a period
through the new admin API (services/payments/fiscal_period_service.py).

Revision ID: 103
Revises: 102
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "103"
down_revision: Union[str, None] = "102"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _enable_rls(conn, table: str) -> None:
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
    conn = op.get_bind()

    op.create_table(
        "fiscal_periods",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="closed"),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.Integer(), nullable=True),
        sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reopened_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_fiscal_periods_range",
        "fiscal_periods",
        ["tenant_id", "period_start", "period_end"],
    )
    op.create_index("ix_fiscal_periods_tenant_id", "fiscal_periods", ["tenant_id"])
    op.create_index("ix_fiscal_periods_period_start", "fiscal_periods", ["period_start"])
    op.create_index("ix_fiscal_periods_period_end", "fiscal_periods", ["period_end"])
    op.create_index("ix_fiscal_periods_status", "fiscal_periods", ["status"])

    _enable_rls(conn, "fiscal_periods")


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text('DROP POLICY IF EXISTS tenant_isolation ON "fiscal_periods"'))
    op.drop_table("fiscal_periods")
