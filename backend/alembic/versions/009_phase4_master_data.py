"""Phase 4 — vendor/employee master data and pending vendor queue.

Revision ID: 009
Revises: 008
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vendor_masters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("master_id", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("abn", sa.String(11), nullable=False, server_default=""),
        sa.Column("billing_address", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("bank", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("default_ledger", sa.String(255), nullable=False, server_default=""),
        sa.Column("default_sub_ledger", sa.String(255), nullable=False, server_default=""),
        sa.Column("payment_terms", sa.String(100), nullable=False, server_default=""),
        sa.Column("status", sa.String(50), nullable=False, server_default=""),
        sa.Column("registered_on", sa.String(32), nullable=False, server_default=""),
        sa.Column("total_spend_ytd", sa.Float(), nullable=False, server_default="0"),
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
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "master_id", name="uq_vendor_master_org_id"),
    )
    op.create_index("ix_vendor_masters_org_id", "vendor_masters", ["org_id"])
    op.create_index("ix_vendor_masters_master_id", "vendor_masters", ["master_id"])

    op.create_table(
        "employee_masters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("master_id", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(255), nullable=False, server_default=""),
        sa.Column("email", sa.String(255), nullable=False, server_default=""),
        sa.Column("whatsapp_number", sa.String(32), nullable=False, server_default=""),
        sa.Column("viber_number", sa.String(32)),
        sa.Column("bank", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("budget", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("ytd_spent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("mtd_spent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("qtd_spent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("claim_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_claim", sa.String(32), nullable=False, server_default=""),
        sa.Column("status", sa.String(50), nullable=False, server_default=""),
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
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "master_id", name="uq_employee_master_org_id"),
    )
    op.create_index("ix_employee_masters_org_id", "employee_masters", ["org_id"])
    op.create_index("ix_employee_masters_master_id", "employee_masters", ["master_id"])

    op.create_table(
        "pending_vendors",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("detected_name", sa.String(255), nullable=False),
        sa.Column("detected_abn", sa.String(11)),
        sa.Column("detected_address", sa.String(500)),
        sa.Column("source_invoice_id", sa.Integer()),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("promoted_master_id", sa.String(100)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["source_invoice_id"], ["invoices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pending_vendors_org_id", "pending_vendors", ["org_id"])
    op.create_index("ix_pending_vendors_status", "pending_vendors", ["status"])


def downgrade() -> None:
    op.drop_index("ix_pending_vendors_status", table_name="pending_vendors")
    op.drop_index("ix_pending_vendors_org_id", table_name="pending_vendors")
    op.drop_table("pending_vendors")
    op.drop_index("ix_employee_masters_master_id", table_name="employee_masters")
    op.drop_index("ix_employee_masters_org_id", table_name="employee_masters")
    op.drop_table("employee_masters")
    op.drop_index("ix_vendor_masters_master_id", table_name="vendor_masters")
    op.drop_index("ix_vendor_masters_org_id", table_name="vendor_masters")
    op.drop_table("vendor_masters")
