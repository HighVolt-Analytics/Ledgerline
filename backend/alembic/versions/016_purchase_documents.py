"""Purchase document types (PO / GRN / invoice) and document links."""

from alembic import op
import sqlalchemy as sa

revision = "016_purchase_documents"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("purchase_document_type", sa.String(16), nullable=True),
    )
    op.create_index(
        "ix_invoices_purchase_document_type",
        "invoices",
        ["purchase_document_type"],
    )

    op.add_column(
        "purchase_orders",
        sa.Column(
            "po_document_id",
            sa.Integer(),
            sa.ForeignKey("invoices.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_purchase_orders_po_document_id",
        "purchase_orders",
        ["po_document_id"],
    )

    op.add_column(
        "goods_receipts",
        sa.Column(
            "grn_invoice_id",
            sa.Integer(),
            sa.ForeignKey("invoices.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_goods_receipts_grn_invoice_id",
        "goods_receipts",
        ["grn_invoice_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_goods_receipts_grn_invoice_id", table_name="goods_receipts")
    op.drop_column("goods_receipts", "grn_invoice_id")
    op.drop_index("ix_purchase_orders_po_document_id", table_name="purchase_orders")
    op.drop_column("purchase_orders", "po_document_id")
    op.drop_index("ix_invoices_purchase_document_type", table_name="invoices")
    op.drop_column("invoices", "purchase_document_type")
