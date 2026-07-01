"""Stripe Connect accounts, transactions, payment attempts, and webhook dedupe.

Revision ID: 038
Revises: 037
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "038"
down_revision: Union[str, None] = "037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TENANT_RLS_TABLES = (
    "stripe_accounts",
    "stripe_balance_snapshots",
    "stripe_transactions",
    "vendor_payment_methods",
)


def _enable_tenant_rls(conn, table: str) -> None:
    if conn.dialect.name != "postgresql":
        return
    conn.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
    conn.execute(
        sa.text(
            f"""
            CREATE POLICY tenant_isolation ON "{table}"
              USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
              )
              WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
              )
            """
        )
    )


def _disable_tenant_rls(conn, table: str) -> None:
    if conn.dialect.name != "postgresql":
        return
    conn.execute(sa.text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"'))


def upgrade() -> None:
    op.create_table(
        "stripe_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("stripe_account_id", sa.String(length=255), nullable=False),
        sa.Column("account_type", sa.String(length=32), nullable=True),
        sa.Column("charges_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payouts_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("details_submitted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("onboarding_status", sa.String(length=32), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stripe_account_id", name="uq_stripe_accounts_stripe_account_id"),
    )
    op.create_index("ix_stripe_accounts_tenant_id", "stripe_accounts", ["tenant_id"])
    op.create_index("ix_stripe_accounts_stripe_account_id", "stripe_accounts", ["stripe_account_id"])

    op.create_table(
        "stripe_balance_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("stripe_account_id", sa.String(length=255), nullable=False),
        sa.Column("available_json", sa.JSON(), nullable=True),
        sa.Column("pending_json", sa.JSON(), nullable=True),
        sa.Column("livemode", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_stripe_balance_snapshots_tenant_id",
        "stripe_balance_snapshots",
        ["tenant_id"],
    )
    op.create_index(
        "ix_stripe_balance_snapshots_stripe_account_id",
        "stripe_balance_snapshots",
        ["stripe_account_id"],
    )

    op.create_table(
        "stripe_transactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("stripe_account_id", sa.String(length=255), nullable=False),
        sa.Column("stripe_transaction_id", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("available_on", sa.Date(), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stripe_transaction_id",
            name="uq_stripe_transactions_stripe_transaction_id",
        ),
    )
    op.create_index("ix_stripe_transactions_tenant_id", "stripe_transactions", ["tenant_id"])
    op.create_index(
        "ix_stripe_transactions_stripe_account_id",
        "stripe_transactions",
        ["stripe_account_id"],
    )
    op.create_index(
        "ix_stripe_transactions_stripe_transaction_id",
        "stripe_transactions",
        ["stripe_transaction_id"],
    )

    op.create_table(
        "payment_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("payment_id", sa.Integer(), nullable=False),
        sa.Column("stripe_payment_intent_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_transfer_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_payout_id", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=True),
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
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_attempts_payment_id", "payment_attempts", ["payment_id"])
    op.create_index(
        "ix_payment_attempts_stripe_payment_intent_id",
        "payment_attempts",
        ["stripe_payment_intent_id"],
    )
    op.create_index("ix_payment_attempts_status", "payment_attempts", ["status"])

    op.create_table(
        "stripe_webhook_events",
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
        sa.UniqueConstraint(
            "stripe_event_id",
            name="uq_stripe_webhook_events_stripe_event_id",
        ),
    )
    op.create_index(
        "ix_stripe_webhook_events_stripe_event_id",
        "stripe_webhook_events",
        ["stripe_event_id"],
    )
    op.create_index(
        "ix_stripe_webhook_events_event_type",
        "stripe_webhook_events",
        ["event_type"],
    )

    op.create_table(
        "vendor_payment_methods",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("vendor_id", sa.Integer(), nullable=False),
        sa.Column("method_type", sa.String(length=32), nullable=True),
        sa.Column("stripe_account_id", sa.String(length=255), nullable=True),
        sa.Column("external_account_last4", sa.String(length=4), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=True),
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
        sa.ForeignKeyConstraint(["vendor_id"], ["vendor_registry.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_vendor_payment_methods_tenant_id",
        "vendor_payment_methods",
        ["tenant_id"],
    )
    op.create_index(
        "ix_vendor_payment_methods_vendor_id",
        "vendor_payment_methods",
        ["vendor_id"],
    )
    op.create_index(
        "ix_vendor_payment_methods_stripe_account_id",
        "vendor_payment_methods",
        ["stripe_account_id"],
    )
    op.create_index("ix_vendor_payment_methods_status", "vendor_payment_methods", ["status"])

    op.add_column("payments", sa.Column("stripe_payment_intent_id", sa.String(length=255), nullable=True))
    op.add_column("payments", sa.Column("stripe_transfer_id", sa.String(length=255), nullable=True))
    op.add_column("payments", sa.Column("stripe_payout_id", sa.String(length=255), nullable=True))
    op.add_column("payments", sa.Column("stripe_charge_id", sa.String(length=255), nullable=True))
    op.add_column("payments", sa.Column("stripe_latest_event_id", sa.String(length=255), nullable=True))
    op.create_index(
        "ix_payments_stripe_payment_intent_id",
        "payments",
        ["stripe_payment_intent_id"],
    )

    conn = op.get_bind()
    for table in _TENANT_RLS_TABLES:
        _enable_tenant_rls(conn, table)


def downgrade() -> None:
    conn = op.get_bind()
    for table in reversed(_TENANT_RLS_TABLES):
        _disable_tenant_rls(conn, table)

    op.drop_index("ix_payments_stripe_payment_intent_id", table_name="payments")
    op.drop_column("payments", "stripe_latest_event_id")
    op.drop_column("payments", "stripe_charge_id")
    op.drop_column("payments", "stripe_payout_id")
    op.drop_column("payments", "stripe_transfer_id")
    op.drop_column("payments", "stripe_payment_intent_id")

    op.drop_index("ix_vendor_payment_methods_status", table_name="vendor_payment_methods")
    op.drop_index(
        "ix_vendor_payment_methods_stripe_account_id",
        table_name="vendor_payment_methods",
    )
    op.drop_index("ix_vendor_payment_methods_vendor_id", table_name="vendor_payment_methods")
    op.drop_index("ix_vendor_payment_methods_tenant_id", table_name="vendor_payment_methods")
    op.drop_table("vendor_payment_methods")

    op.drop_index("ix_stripe_webhook_events_event_type", table_name="stripe_webhook_events")
    op.drop_index("ix_stripe_webhook_events_stripe_event_id", table_name="stripe_webhook_events")
    op.drop_table("stripe_webhook_events")

    op.drop_index("ix_payment_attempts_status", table_name="payment_attempts")
    op.drop_index("ix_payment_attempts_stripe_payment_intent_id", table_name="payment_attempts")
    op.drop_index("ix_payment_attempts_payment_id", table_name="payment_attempts")
    op.drop_table("payment_attempts")

    op.drop_index("ix_stripe_transactions_stripe_transaction_id", table_name="stripe_transactions")
    op.drop_index("ix_stripe_transactions_stripe_account_id", table_name="stripe_transactions")
    op.drop_index("ix_stripe_transactions_tenant_id", table_name="stripe_transactions")
    op.drop_table("stripe_transactions")

    op.drop_index(
        "ix_stripe_balance_snapshots_stripe_account_id",
        table_name="stripe_balance_snapshots",
    )
    op.drop_index("ix_stripe_balance_snapshots_tenant_id", table_name="stripe_balance_snapshots")
    op.drop_table("stripe_balance_snapshots")

    op.drop_index("ix_stripe_accounts_stripe_account_id", table_name="stripe_accounts")
    op.drop_index("ix_stripe_accounts_tenant_id", table_name="stripe_accounts")
    op.drop_table("stripe_accounts")
