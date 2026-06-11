"""Purchase orders, goods receipts, and payments workflow.

Revision ID: 012
Revises: 011
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("po_number", sa.String(100), nullable=False),
        sa.Column("vendor", sa.String(255)),
        sa.Column("po_date", sa.Date()),
        sa.Column("item", sa.String(255)),
        sa.Column("requestor", sa.String(255)),
        sa.Column("po_qty", sa.Numeric(12, 4), server_default="1"),
        sa.Column("po_unit_price", sa.Numeric(12, 4), server_default="0"),
        sa.Column("invoice_id", sa.Integer()),
        sa.Column("variance_approved", sa.Boolean(), server_default=sa.false()),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "matched",
                "variance_pending",
                "closed",
                name="purchase_order_status",
            ),
            server_default="open",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_purchase_orders_org_id", "purchase_orders", ["org_id"])
    op.create_index("ix_purchase_orders_po_number", "purchase_orders", ["po_number"])
    op.create_index(
        "ix_purchase_orders_org_po",
        "purchase_orders",
        ["org_id", "po_number"],
        unique=True,
    )

    op.create_table(
        "goods_receipts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("grn_qty", sa.Numeric(12, 4), nullable=False),
        sa.Column("grn_date", sa.Date()),
        sa.Column("receiver", sa.String(255)),
        sa.Column("condition_note", sa.String(255)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_goods_receipts_purchase_order_id",
        "goods_receipts",
        ["purchase_order_id"],
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("vendor", sa.String(255)),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="AUD"),
        sa.Column(
            "status",
            sa.Enum(
                "queue",
                "awaiting",
                "scheduled",
                "paid",
                "failed",
                name="payment_status",
            ),
            server_default="queue",
        ),
        sa.Column("due_date", sa.Date()),
        sa.Column("scheduled_date", sa.Date()),
        sa.Column("paid_date", sa.DateTime(timezone=True)),
        sa.Column("invoice_approved_by", sa.Integer()),
        sa.Column("approvers", sa.JSON()),
        sa.Column("payment_intent", sa.String(255)),
        sa.Column("failure_reason", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payments_org_id", "payments", ["org_id"])
    op.create_index("ix_payments_invoice_id", "payments", ["invoice_id"])
    op.create_index(
        "ix_payments_org_invoice",
        "payments",
        ["org_id", "invoice_id"],
        unique=True,
    )
    op.create_index("ix_payments_status", "payments", ["status"])


def downgrade() -> None:
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index("ix_payments_org_invoice", table_name="payments")
    op.drop_index("ix_payments_invoice_id", table_name="payments")
    op.drop_index("ix_payments_org_id", table_name="payments")
    op.drop_table("payments")
    op.execute("DROP TYPE IF EXISTS payment_status")

    op.drop_index("ix_goods_receipts_purchase_order_id", table_name="goods_receipts")
    op.drop_table("goods_receipts")

    op.drop_index("ix_purchase_orders_org_po", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_po_number", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_org_id", table_name="purchase_orders")
    op.drop_table("purchase_orders")
    op.execute("DROP TYPE IF EXISTS purchase_order_status")
