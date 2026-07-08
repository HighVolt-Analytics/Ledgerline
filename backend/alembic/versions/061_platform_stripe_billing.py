"""Platform Stripe subscription billing and pending signups.

Revision ID: 061
Revises: 060
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "061"
down_revision: Union[str, None] = "060"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenant_billing", sa.Column("billing_country", sa.String(length=2), nullable=True))
    op.add_column("tenant_billing", sa.Column("billing_currency", sa.String(length=3), nullable=True))
    op.add_column("tenant_billing", sa.Column("stripe_customer_id", sa.String(length=255), nullable=True))
    op.add_column(
        "tenant_billing",
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
    )
    op.add_column("tenant_billing", sa.Column("stripe_price_id", sa.String(length=255), nullable=True))
    op.add_column(
        "tenant_billing",
        sa.Column("subscription_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "tenant_billing",
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenant_billing",
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenant_billing",
        sa.Column("cancel_at_period_end", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("tenant_billing", sa.Column("monthly_credits", sa.Integer(), nullable=True))
    op.add_column("tenant_billing", sa.Column("user_limit", sa.Integer(), nullable=True))
    op.create_index("ix_tenant_billing_stripe_customer_id", "tenant_billing", ["stripe_customer_id"])
    op.create_index(
        "ix_tenant_billing_stripe_subscription_id",
        "tenant_billing",
        ["stripe_subscription_id"],
    )

    op.add_column(
        "credit_ledger_entries",
        sa.Column("stripe_checkout_session_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "credit_ledger_entries",
        sa.Column("stripe_payment_intent_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "credit_ledger_entries",
        sa.Column("stripe_invoice_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_credit_ledger_stripe_checkout_session_id",
        "credit_ledger_entries",
        ["stripe_checkout_session_id"],
    )
    op.create_index(
        "ix_credit_ledger_stripe_invoice_id",
        "credit_ledger_entries",
        ["stripe_invoice_id"],
    )

    op.create_table(
        "pending_signup_billing_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("signup_token", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("organisation_name", sa.String(length=255), nullable=False),
        sa.Column("organisation_slug", sa.String(length=100), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("plan_code", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("monthly_credits", sa.Integer(), nullable=False),
        sa.Column("user_limit", sa.Integer(), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("industry", sa.String(length=64), nullable=True),
        sa.Column("stripe_checkout_session_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signup_token", name="uq_pending_signup_signup_token"),
        sa.UniqueConstraint(
            "stripe_checkout_session_id",
            name="uq_pending_signup_checkout_session",
        ),
    )
    op.create_index(
        "ix_pending_signup_billing_sessions_email",
        "pending_signup_billing_sessions",
        ["email"],
    )
    op.create_index(
        "ix_pending_signup_billing_sessions_status",
        "pending_signup_billing_sessions",
        ["status"],
    )

    op.create_table(
        "platform_billing_webhook_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stripe_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stripe_event_id", name="uq_platform_billing_webhook_event_id"),
    )


def downgrade() -> None:
    op.drop_table("platform_billing_webhook_events")
    op.drop_table("pending_signup_billing_sessions")
    op.drop_index("ix_credit_ledger_stripe_invoice_id", table_name="credit_ledger_entries")
    op.drop_index(
        "ix_credit_ledger_stripe_checkout_session_id",
        table_name="credit_ledger_entries",
    )
    op.drop_column("credit_ledger_entries", "stripe_invoice_id")
    op.drop_column("credit_ledger_entries", "stripe_payment_intent_id")
    op.drop_column("credit_ledger_entries", "stripe_checkout_session_id")
    op.drop_index("ix_tenant_billing_stripe_subscription_id", table_name="tenant_billing")
    op.drop_index("ix_tenant_billing_stripe_customer_id", table_name="tenant_billing")
    op.drop_column("tenant_billing", "user_limit")
    op.drop_column("tenant_billing", "monthly_credits")
    op.drop_column("tenant_billing", "cancel_at_period_end")
    op.drop_column("tenant_billing", "current_period_end")
    op.drop_column("tenant_billing", "current_period_start")
    op.drop_column("tenant_billing", "subscription_status")
    op.drop_column("tenant_billing", "stripe_price_id")
    op.drop_column("tenant_billing", "stripe_subscription_id")
    op.drop_column("tenant_billing", "stripe_customer_id")
    op.drop_column("tenant_billing", "billing_currency")
    op.drop_column("tenant_billing", "billing_country")
