"""Enable tenant RLS on tables added after the original RLS rollout.

Revision ID: 052
Revises: 051
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "052"
down_revision: Union[str, None] = "051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_TABLES = (
    "connected_viber_accounts",
    "payment_execution_instructions",
    "customer_masters",
    "customer_registry",
    "sales_orders",
    "delivery_notes",
    "collections",
)


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


def _disable_rls(conn, table: str) -> None:
    if conn.dialect.name != "postgresql":
        return
    conn.execute(sa.text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"'))
    conn.execute(sa.text(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY'))
    conn.execute(sa.text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))


def upgrade() -> None:
    conn = op.get_bind()
    for table in _RLS_TABLES:
        if conn.dialect.name == "postgresql":
            exists = conn.execute(
                sa.text(
                    """
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = :name
                    """
                ),
                {"name": table},
            ).scalar()
            if not exists:
                continue
        _enable_rls(conn, table)


def downgrade() -> None:
    conn = op.get_bind()
    for table in reversed(_RLS_TABLES):
        if conn.dialect.name == "postgresql":
            exists = conn.execute(
                sa.text(
                    """
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = :name
                    """
                ),
                {"name": table},
            ).scalar()
            if not exists:
                continue
        _disable_rls(conn, table)
