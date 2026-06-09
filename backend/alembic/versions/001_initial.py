"""initial schema

Revision ID: 001
Revises:
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("vendor", sa.String(255)),
        sa.Column("abn", sa.String(11)),
        sa.Column("invoice_no", sa.String(100)),
        sa.Column("invoice_date", sa.Date()),
        sa.Column("due_date", sa.Date()),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2)),
        sa.Column("gst", sa.Numeric(12, 2)),
        sa.Column("total", sa.Numeric(12, 2)),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "parsing", "validating", "mapping", "journaling",
                "reconciling", "processed", "exception", "duplicate_skipped",
                name="invoice_status",
            ),
            nullable=False,
        ),
        sa.Column("file_hash", sa.String(64), unique=True),
        sa.Column("raw_file_path", sa.Text()),
        sa.Column("validation_results", sa.Text()),
        sa.Column("account_code", sa.String(20)),
        sa.Column("account_name", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invoices_invoice_no", "invoices", ["invoice_no"])
    op.create_index("ix_invoices_status", "invoices", ["status"])

    op.create_table(
        "line_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id", ondelete="CASCADE")),
        sa.Column("description", sa.Text()),
        sa.Column("qty", sa.Numeric(12, 4)),
        sa.Column("unit_price", sa.Numeric(12, 2)),
        sa.Column("amount", sa.Numeric(12, 2)),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id", ondelete="CASCADE")),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("account_code", sa.String(20), nullable=False),
        sa.Column("account_name", sa.String(255), nullable=False),
        sa.Column("debit", sa.Numeric(12, 2), nullable=False),
        sa.Column("credit", sa.Numeric(12, 2), nullable=False),
        sa.Column("entry_type", sa.Enum("debit", "credit", name="entry_type"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "daily_reconciliations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("total_invoices", sa.Integer(), nullable=False),
        sa.Column("total_ap_credits", sa.Numeric(14, 2), nullable=False),
        sa.Column("total_debits", sa.Numeric(14, 2), nullable=False),
        sa.Column("total_credits", sa.Numeric(14, 2), nullable=False),
        sa.Column("is_balanced", sa.Boolean(), nullable=False),
        sa.Column("halted", sa.Boolean(), nullable=False),
        sa.Column("halt_reason", sa.Text()),
        sa.Column("run_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("correlation_id", sa.String(36)),
        sa.Column("event", sa.String(100), nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id", ondelete="SET NULL")),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("daily_reconciliations")
    op.drop_table("journal_entries")
    op.drop_table("line_items")
    op.drop_table("invoices")
    op.execute("DROP TYPE IF EXISTS entry_type")
    op.execute("DROP TYPE IF EXISTS invoice_status")
