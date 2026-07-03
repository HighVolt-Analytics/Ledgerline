"""Tenant billing, credit ledger, platform credit settings.

Revision ID: 053
Revises: 052
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "053"
down_revision: Union[str, None] = "052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_credit_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("credits_per_page", sa.Integer(), server_default="5", nullable=False),
        sa.Column("universal_credits_per_page", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("topup_factor_in", sa.Numeric(12, 4), server_default="1", nullable=False),
        sa.Column("topup_factor_sg", sa.Numeric(12, 4), server_default="10", nullable=False),
        sa.Column("topup_factor_au", sa.Numeric(12, 4), server_default="5", nullable=False),
        sa.Column(
            "azure_di_prebuilt_per_1000_pages_usd",
            sa.Numeric(12, 6),
            server_default="10.00",
            nullable=False,
        ),
        sa.Column(
            "azure_di_read_per_1000_pages_usd",
            sa.Numeric(12, 6),
            server_default="1.50",
            nullable=False,
        ),
        sa.Column(
            "azure_foundry_input_per_1m_tokens_usd",
            sa.Numeric(12, 6),
            server_default="2.50",
            nullable=False,
        ),
        sa.Column(
            "azure_foundry_output_per_1m_tokens_usd",
            sa.Numeric(12, 6),
            server_default="10.00",
            nullable=False,
        ),
        sa.Column(
            "azure_openai_mini_input_per_1m_tokens_usd",
            sa.Numeric(12, 6),
            server_default="0.15",
            nullable=False,
        ),
        sa.Column(
            "azure_openai_mini_output_per_1m_tokens_usd",
            sa.Numeric(12, 6),
            server_default="0.60",
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(sa.text("INSERT INTO platform_credit_settings (id) VALUES (1)"))

    op.create_table(
        "tenant_billing",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("plan", sa.String(length=20), server_default="free", nullable=False),
        sa.Column("credit_balance", sa.Integer(), server_default="0", nullable=False),
        sa.Column("credits_per_page_override", sa.Integer(), nullable=True),
        sa.Column("billing_anchor_date", sa.Date(), nullable=False),
        sa.Column("last_monthly_grant_at", sa.Date(), nullable=True),
        sa.Column("enterprise_monthly_credits", sa.Integer(), nullable=True),
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
        sa.PrimaryKeyConstraint("tenant_id"),
    )

    op.create_table(
        "credit_ledger_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("credits_per_page", sa.Integer(), nullable=True),
        sa.Column("credits_delta", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("plan_at_event", sa.String(length=20), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("amount_paid", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency_code", sa.String(length=3), nullable=True),
        sa.Column("azure_cost_usd", sa.Numeric(14, 6), nullable=True),
        sa.Column(
            "azure_cost_breakdown_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("filename", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_credit_ledger_idempotency"),
    )
    op.create_index("ix_credit_ledger_tenant_id", "credit_ledger_entries", ["tenant_id"])
    op.create_index("ix_credit_ledger_event_type", "credit_ledger_entries", ["event_type"])
    op.create_index("ix_credit_ledger_invoice_id", "credit_ledger_entries", ["invoice_id"])
    op.create_index("ix_credit_ledger_created_at", "credit_ledger_entries", ["created_at"])

    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        for table in ("tenant_billing", "credit_ledger_entries"):
            op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            op.execute(
                sa.text(
                    f"""
                    CREATE POLICY tenant_isolation ON {table}
                    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                    """
                )
            )


def downgrade() -> None:
    op.drop_table("credit_ledger_entries")
    op.drop_table("tenant_billing")
    op.drop_table("platform_credit_settings")
