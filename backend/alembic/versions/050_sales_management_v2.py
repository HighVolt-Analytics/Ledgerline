"""Sales management v2 — customers, sales orders, delivery notes, collections.

Revision ID: 051
Revises: 050
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "051"
down_revision: Union[str, None] = "050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customer_masters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("master_id", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("abn", sa.String(11), nullable=False, server_default=""),
        sa.Column("billing_address", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("default_ledger", sa.String(255), nullable=False, server_default=""),
        sa.Column("default_sub_ledger", sa.String(255), nullable=False, server_default=""),
        sa.Column("payment_terms", sa.String(100), nullable=False, server_default=""),
        sa.Column("status", sa.String(50), nullable=False, server_default=""),
        sa.Column("registered_on", sa.String(32), nullable=False, server_default=""),
        sa.Column("total_revenue_ytd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("invoice_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("match_confidence", sa.Float(), nullable=False, server_default="0"),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "master_id", name="uq_customer_master_tenant_id"),
    )
    op.create_index("ix_customer_masters_tenant_id", "customer_masters", ["tenant_id"])
    op.create_index("ix_customer_masters_master_id", "customer_masters", ["master_id"])

    op.create_table(
        "customer_registry",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("customer_slug", sa.String(100), nullable=False),
        sa.Column("customer_name", sa.String(255), nullable=False),
        sa.Column("sender_pattern", sa.String(255), nullable=False),
        sa.Column("abn", sa.String(11)),
        sa.Column("approved", sa.Boolean(), server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "customer_slug", name="uq_customer_tenant_slug"),
    )
    op.create_index("ix_customer_registry_tenant_id", "customer_registry", ["tenant_id"])
    op.create_index("ix_customer_registry_customer_slug", "customer_registry", ["customer_slug"])
    op.create_index("ix_customer_registry_sender_pattern", "customer_registry", ["sender_pattern"])

    op.create_table(
        "sales_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("so_number", sa.String(100), nullable=False),
        sa.Column("customer", sa.String(255)),
        sa.Column("so_date", sa.Date()),
        sa.Column("item", sa.String(255)),
        sa.Column("requestor", sa.String(255)),
        sa.Column("so_qty", sa.Numeric(12, 4), server_default="1"),
        sa.Column("so_unit_price", sa.Numeric(12, 4), server_default="0"),
        sa.Column("so_uom", sa.String(32)),
        sa.Column("so_currency", sa.String(3)),
        sa.Column("invoice_id", sa.Integer()),
        sa.Column("so_document_id", sa.Integer()),
        sa.Column("variance_approved", sa.Boolean(), server_default=sa.false()),
        sa.Column("ledger", sa.String(255)),
        sa.Column("sub_ledger", sa.String(255)),
        sa.Column("tax_account", sa.String(100)),
        sa.Column("receivable_account", sa.String(100)),
        sa.Column("sales_rule_id", sa.String(100)),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "matched",
                "variance_pending",
                "closed",
                name="sales_order_status",
            ),
            server_default="open",
        ),
        sa.Column("three_way_match_status", sa.String(32)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["so_document_id"], ["invoices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sales_orders_tenant_id", "sales_orders", ["tenant_id"])
    op.create_index("ix_sales_orders_so_number", "sales_orders", ["so_number"])
    op.create_index(
        "ix_sales_orders_tenant_so",
        "sales_orders",
        ["tenant_id", "so_number"],
        unique=True,
    )
    op.create_index("ix_sales_orders_invoice_id", "sales_orders", ["invoice_id"])
    op.create_index("ix_sales_orders_so_document_id", "sales_orders", ["so_document_id"])
    op.create_index("ix_sales_orders_three_way_match_status", "sales_orders", ["three_way_match_status"])

    op.create_table(
        "delivery_notes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), nullable=False),
        sa.Column("dn_qty", sa.Numeric(12, 4), nullable=False),
        sa.Column("dn_uom", sa.String(32)),
        sa.Column("dn_currency", sa.String(3)),
        sa.Column("dn_date", sa.Date()),
        sa.Column("shipper", sa.String(255)),
        sa.Column("condition_note", sa.String(255)),
        sa.Column("dn_invoice_id", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dn_invoice_id"], ["invoices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delivery_notes_tenant_id", "delivery_notes", ["tenant_id"])
    op.create_index("ix_delivery_notes_sales_order_id", "delivery_notes", ["sales_order_id"])
    op.create_index("ix_delivery_notes_dn_invoice_id", "delivery_notes", ["dn_invoice_id"])

    op.create_table(
        "collections",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("customer_registry_id", sa.Integer()),
        sa.Column("customer", sa.String(255)),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="AUD"),
        sa.Column(
            "status",
            sa.Enum(
                "queue",
                "awaiting",
                "received",
                "failed",
                name="collection_status",
            ),
            server_default="queue",
        ),
        sa.Column("due_date", sa.Date()),
        sa.Column("received_date", sa.DateTime(timezone=True)),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("stripe_payment_intent_id", sa.String(255)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_registry_id"], ["customer_registry.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_collections_tenant_id", "collections", ["tenant_id"])
    op.create_index("ix_collections_invoice_id", "collections", ["invoice_id"])
    op.create_index(
        "ix_collections_tenant_invoice",
        "collections",
        ["tenant_id", "invoice_id"],
        unique=True,
    )
    op.create_index("ix_collections_status", "collections", ["status"])
    op.create_index("ix_collections_customer_registry_id", "collections", ["customer_registry_id"])

    op.add_column(
        "invoices",
        sa.Column("sales_document_type", sa.String(16), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("so_reference", sa.String(100), nullable=True),
    )
    op.create_index(
        "ix_invoices_sales_document_type",
        "invoices",
        ["sales_document_type"],
    )
    op.create_index(
        "ix_invoices_so_reference",
        "invoices",
        ["so_reference"],
    )


def downgrade() -> None:
    op.drop_index("ix_invoices_so_reference", table_name="invoices")
    op.drop_index("ix_invoices_sales_document_type", table_name="invoices")
    op.drop_column("invoices", "so_reference")
    op.drop_column("invoices", "sales_document_type")

    op.drop_index("ix_collections_customer_registry_id", table_name="collections")
    op.drop_index("ix_collections_status", table_name="collections")
    op.drop_index("ix_collections_tenant_invoice", table_name="collections")
    op.drop_index("ix_collections_invoice_id", table_name="collections")
    op.drop_index("ix_collections_tenant_id", table_name="collections")
    op.drop_table("collections")
    op.execute("DROP TYPE IF EXISTS collection_status")

    op.drop_index("ix_delivery_notes_dn_invoice_id", table_name="delivery_notes")
    op.drop_index("ix_delivery_notes_sales_order_id", table_name="delivery_notes")
    op.drop_index("ix_delivery_notes_tenant_id", table_name="delivery_notes")
    op.drop_table("delivery_notes")

    op.drop_index("ix_sales_orders_three_way_match_status", table_name="sales_orders")
    op.drop_index("ix_sales_orders_so_document_id", table_name="sales_orders")
    op.drop_index("ix_sales_orders_invoice_id", table_name="sales_orders")
    op.drop_index("ix_sales_orders_tenant_so", table_name="sales_orders")
    op.drop_index("ix_sales_orders_so_number", table_name="sales_orders")
    op.drop_index("ix_sales_orders_tenant_id", table_name="sales_orders")
    op.drop_table("sales_orders")
    op.execute("DROP TYPE IF EXISTS sales_order_status")

    op.drop_index("ix_customer_registry_sender_pattern", table_name="customer_registry")
    op.drop_index("ix_customer_registry_customer_slug", table_name="customer_registry")
    op.drop_index("ix_customer_registry_tenant_id", table_name="customer_registry")
    op.drop_table("customer_registry")

    op.drop_index("ix_customer_masters_master_id", table_name="customer_masters")
    op.drop_index("ix_customer_masters_tenant_id", table_name="customer_masters")
    op.drop_table("customer_masters")
