"""Add tenant_id to line_items, journal_entries, goods_receipts, meta_webhook_dedupe.

Revision ID: 033
Revises: 032
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "033"
down_revision: Union[str, None] = "032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INVOICE_CHILD = ("line_items", "journal_entries")
_RLS_TABLES = ("line_items", "journal_entries", "goods_receipts", "meta_webhook_dedupe")


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

    for table in _INVOICE_CHILD:
        op.add_column(table, sa.Column("tenant_id", sa.Uuid(), nullable=True))
        conn.execute(
            sa.text(
                f"""
                UPDATE "{table}" AS child
                SET tenant_id = inv.tenant_id
                FROM invoices AS inv
                WHERE child.invoice_id = inv.id
                """
            )
        )
        conn.execute(sa.text(f'DELETE FROM "{table}" WHERE tenant_id IS NULL'))
        op.alter_column(table, "tenant_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_tenant_id",
            table,
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    op.add_column("goods_receipts", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    conn.execute(
        sa.text(
            """
            UPDATE goods_receipts AS grn
            SET tenant_id = po.tenant_id
            FROM purchase_orders AS po
            WHERE grn.purchase_order_id = po.id
            """
        )
    )
    conn.execute(sa.text("DELETE FROM goods_receipts WHERE tenant_id IS NULL"))
    op.alter_column("goods_receipts", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_goods_receipts_tenant_id",
        "goods_receipts",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_goods_receipts_tenant_id", "goods_receipts", ["tenant_id"])

    op.drop_constraint(
        "meta_webhook_dedupe_message_mid_key",
        "meta_webhook_dedupe",
        type_="unique",
    )
    conn.execute(sa.text("DELETE FROM meta_webhook_dedupe"))
    op.add_column("meta_webhook_dedupe", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.alter_column("meta_webhook_dedupe", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_meta_webhook_dedupe_tenant_id",
        "meta_webhook_dedupe",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_meta_webhook_dedupe_tenant_id", "meta_webhook_dedupe", ["tenant_id"])
    op.create_unique_constraint(
        "uq_meta_webhook_dedupe_tenant_mid",
        "meta_webhook_dedupe",
        ["tenant_id", "message_mid"],
    )

    if conn.dialect.name == "postgresql":
        for table in _RLS_TABLES:
            _enable_rls(conn, table)


def downgrade() -> None:
    conn = op.get_bind()

    if conn.dialect.name == "postgresql":
        for table in _RLS_TABLES:
            conn.execute(
                sa.text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
            )

    op.drop_constraint("uq_meta_webhook_dedupe_tenant_mid", "meta_webhook_dedupe", type_="unique")
    op.drop_index("ix_meta_webhook_dedupe_tenant_id", table_name="meta_webhook_dedupe")
    op.drop_constraint("fk_meta_webhook_dedupe_tenant_id", "meta_webhook_dedupe", type_="foreignkey")
    op.drop_column("meta_webhook_dedupe", "tenant_id")
    op.create_unique_constraint(
        "meta_webhook_dedupe_message_mid_key",
        "meta_webhook_dedupe",
        ["message_mid"],
    )

    op.drop_index("ix_goods_receipts_tenant_id", table_name="goods_receipts")
    op.drop_constraint("fk_goods_receipts_tenant_id", "goods_receipts", type_="foreignkey")
    op.drop_column("goods_receipts", "tenant_id")

    for table in reversed(_INVOICE_CHILD):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_constraint(f"fk_{table}_tenant_id", table, type_="foreignkey")
        op.drop_column(table, "tenant_id")
