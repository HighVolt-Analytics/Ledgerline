"""Line tables for PO/GRN/SO/DN three-way match.

Revision ID: 072
Revises: 071
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "072"
down_revision: Union[str, None] = "071"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_TABLES = (
    "purchase_order_lines",
    "goods_receipt_lines",
    "sales_order_lines",
    "delivery_note_lines",
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


def _create_index_if_missing(inspector, table: str, name: str, columns: list[str]) -> None:
    existing = {idx["name"] for idx in inspector.get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns)


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    if not inspector.has_table("purchase_order_lines"):
        op.create_table(
            "purchase_order_lines",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("purchase_order_id", sa.Integer(), nullable=False),
            sa.Column("line_no", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("sku", sa.String(length=100), nullable=True),
            sa.Column("qty", sa.Numeric(12, 4), nullable=True),
            sa.Column("uom", sa.String(length=32), nullable=True),
            sa.Column("unit_price", sa.Numeric(12, 4), nullable=True),
            sa.Column("line_value", sa.Numeric(12, 2), nullable=True),
            sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    inspector = inspect(conn)
    _create_index_if_missing(
        inspector, "purchase_order_lines", "ix_purchase_order_lines_tenant_id", ["tenant_id"]
    )
    _create_index_if_missing(
        inspector,
        "purchase_order_lines",
        "ix_purchase_order_lines_purchase_order_id",
        ["purchase_order_id"],
    )

    if not inspector.has_table("goods_receipt_lines"):
        op.create_table(
            "goods_receipt_lines",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("goods_receipt_id", sa.Integer(), nullable=False),
            sa.Column("purchase_order_line_id", sa.Integer(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("sku", sa.String(length=100), nullable=True),
            sa.Column("qty", sa.Numeric(12, 4), nullable=True),
            sa.Column("uom", sa.String(length=32), nullable=True),
            sa.ForeignKeyConstraint(["goods_receipt_id"], ["goods_receipts.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["purchase_order_line_id"],
                ["purchase_order_lines.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    inspector = inspect(conn)
    _create_index_if_missing(
        inspector, "goods_receipt_lines", "ix_goods_receipt_lines_tenant_id", ["tenant_id"]
    )
    _create_index_if_missing(
        inspector,
        "goods_receipt_lines",
        "ix_goods_receipt_lines_goods_receipt_id",
        ["goods_receipt_id"],
    )
    _create_index_if_missing(
        inspector,
        "goods_receipt_lines",
        "ix_goods_receipt_lines_purchase_order_line_id",
        ["purchase_order_line_id"],
    )

    if not inspector.has_table("sales_order_lines"):
        op.create_table(
            "sales_order_lines",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("sales_order_id", sa.Integer(), nullable=False),
            sa.Column("line_no", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("sku", sa.String(length=100), nullable=True),
            sa.Column("qty", sa.Numeric(12, 4), nullable=True),
            sa.Column("uom", sa.String(length=32), nullable=True),
            sa.Column("unit_price", sa.Numeric(12, 4), nullable=True),
            sa.Column("line_value", sa.Numeric(12, 2), nullable=True),
            sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    inspector = inspect(conn)
    _create_index_if_missing(
        inspector, "sales_order_lines", "ix_sales_order_lines_tenant_id", ["tenant_id"]
    )
    _create_index_if_missing(
        inspector, "sales_order_lines", "ix_sales_order_lines_sales_order_id", ["sales_order_id"]
    )

    if not inspector.has_table("delivery_note_lines"):
        op.create_table(
            "delivery_note_lines",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("delivery_note_id", sa.Integer(), nullable=False),
            sa.Column("sales_order_line_id", sa.Integer(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("sku", sa.String(length=100), nullable=True),
            sa.Column("qty", sa.Numeric(12, 4), nullable=True),
            sa.Column("uom", sa.String(length=32), nullable=True),
            sa.ForeignKeyConstraint(["delivery_note_id"], ["delivery_notes.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["sales_order_line_id"],
                ["sales_order_lines.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    inspector = inspect(conn)
    _create_index_if_missing(
        inspector, "delivery_note_lines", "ix_delivery_note_lines_tenant_id", ["tenant_id"]
    )
    _create_index_if_missing(
        inspector,
        "delivery_note_lines",
        "ix_delivery_note_lines_delivery_note_id",
        ["delivery_note_id"],
    )
    _create_index_if_missing(
        inspector,
        "delivery_note_lines",
        "ix_delivery_note_lines_sales_order_line_id",
        ["sales_order_line_id"],
    )
    # Backfill one synthetic line from header fields for legacy rows.
    conn.execute(
        sa.text(
            """
            INSERT INTO purchase_order_lines (
                tenant_id, purchase_order_id, line_no, description, qty, uom, unit_price, line_value
            )
            SELECT
                po.tenant_id,
                po.id,
                1,
                po.item,
                po.po_qty,
                po.po_uom,
                po.po_unit_price,
                ROUND(po.po_qty * po.po_unit_price, 2)
            FROM purchase_orders po
            WHERE NOT EXISTS (
                SELECT 1 FROM purchase_order_lines pol WHERE pol.purchase_order_id = po.id
            )
            """
        )
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO sales_order_lines (
                tenant_id, sales_order_id, line_no, description, qty, uom, unit_price, line_value
            )
            SELECT
                so.tenant_id,
                so.id,
                1,
                so.item,
                so.so_qty,
                so.so_uom,
                so.so_unit_price,
                ROUND(so.so_qty * so.so_unit_price, 2)
            FROM sales_orders so
            WHERE NOT EXISTS (
                SELECT 1 FROM sales_order_lines sol WHERE sol.sales_order_id = so.id
            )
            """
        )
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO goods_receipt_lines (
                tenant_id, goods_receipt_id, purchase_order_line_id, description, qty, uom
            )
            SELECT
                grn.tenant_id,
                grn.id,
                (
                    SELECT pol.id FROM purchase_order_lines pol
                    WHERE pol.purchase_order_id = grn.purchase_order_id
                    ORDER BY pol.line_no, pol.id
                    LIMIT 1
                ),
                NULL,
                grn.grn_qty,
                grn.grn_uom
            FROM goods_receipts grn
            WHERE NOT EXISTS (
                SELECT 1 FROM goods_receipt_lines grl WHERE grl.goods_receipt_id = grn.id
            )
            """
        )
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO delivery_note_lines (
                tenant_id, delivery_note_id, sales_order_line_id, description, qty, uom
            )
            SELECT
                dn.tenant_id,
                dn.id,
                (
                    SELECT sol.id FROM sales_order_lines sol
                    WHERE sol.sales_order_id = dn.sales_order_id
                    ORDER BY sol.line_no, sol.id
                    LIMIT 1
                ),
                NULL,
                dn.dn_qty,
                dn.dn_uom
            FROM delivery_notes dn
            WHERE NOT EXISTS (
                SELECT 1 FROM delivery_note_lines dnl WHERE dnl.delivery_note_id = dn.id
            )
            """
        )
    )

    for table in _RLS_TABLES:
        _enable_rls(conn, table)


def downgrade() -> None:
    conn = op.get_bind()
    for table in reversed(_RLS_TABLES):
        _disable_rls(conn, table)

    op.drop_table("delivery_note_lines")
    op.drop_table("sales_order_lines")
    op.drop_table("goods_receipt_lines")
    op.drop_table("purchase_order_lines")
