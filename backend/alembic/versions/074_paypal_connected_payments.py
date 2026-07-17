"""PayPal connected payments schema beside Stripe Connect.

Revision ID: 074
Revises: 073
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "074"
down_revision: Union[str, None] = "073"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(conn, table: str) -> bool:
    return inspect(conn).has_table(table)


def _has_column(conn, table: str, column: str) -> bool:
    if not _has_table(conn, table):
        return False
    return column in {c["name"] for c in inspect(conn).get_columns(table)}


def _has_index(conn, table: str, index_name: str) -> bool:
    if not _has_table(conn, table):
        return False
    return index_name in {idx["name"] for idx in inspect(conn).get_indexes(table)}


def _enable_tenant_rls(conn, table: str) -> None:
    if conn.dialect.name != "postgresql":
        return
    conn.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
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

    if not _has_table(conn, "tenant_payment_provider_accounts"):
        op.create_table(
            "tenant_payment_provider_accounts",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("provider_account_id", sa.String(length=255), nullable=False),
            sa.Column("provider_merchant_id", sa.String(length=255), nullable=True),
            sa.Column("provider_email", sa.String(length=255), nullable=True),
            sa.Column("display_name", sa.String(length=255), nullable=True),
            sa.Column("country", sa.String(length=2), nullable=True),
            sa.Column("default_currency", sa.String(length=3), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("onboarding_status", sa.String(length=64), nullable=True),
            sa.Column("payments_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("payouts_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("balance_visibility", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("transactions_visibility", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("encrypted_access_token", sa.Text(), nullable=True),
            sa.Column("encrypted_refresh_token", sa.Text(), nullable=True),
            sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("tracking_id", sa.String(length=128), nullable=True),
            sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_balance_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_transaction_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error_code", sa.String(length=64), nullable=True),
            sa.Column("last_error_message", sa.String(length=512), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "provider",
                "provider_account_id",
                name="uq_tenant_payment_provider_accounts_tenant_provider_account",
            ),
        )
        op.create_index("ix_tenant_payment_provider_accounts_tenant_id", "tenant_payment_provider_accounts", ["tenant_id"])
        op.create_index("ix_tenant_payment_provider_accounts_provider", "tenant_payment_provider_accounts", ["provider"])
        op.create_index("ix_tenant_payment_provider_accounts_provider_account_id", "tenant_payment_provider_accounts", ["provider_account_id"])
        op.create_index("ix_tenant_payment_provider_accounts_provider_merchant_id", "tenant_payment_provider_accounts", ["provider_merchant_id"])
        op.create_index("ix_tenant_payment_provider_accounts_status", "tenant_payment_provider_accounts", ["status"])
        op.create_index("ix_tenant_payment_provider_accounts_tracking_id", "tenant_payment_provider_accounts", ["tracking_id"])
        _enable_tenant_rls(conn, "tenant_payment_provider_accounts")

    if not _has_table(conn, "provider_transactions"):
        op.create_table(
            "provider_transactions",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("provider_account_id", sa.String(length=255), nullable=False),
            sa.Column("provider_transaction_id", sa.String(length=255), nullable=False),
            sa.Column("transaction_type", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=64), nullable=True),
            sa.Column("currency", sa.String(length=3), nullable=True),
            sa.Column("gross_amount", sa.String(length=32), nullable=True),
            sa.Column("fee_amount", sa.String(length=32), nullable=True),
            sa.Column("net_amount", sa.String(length=32), nullable=True),
            sa.Column("recipient", sa.String(length=255), nullable=True),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("raw_payload_hash", sa.String(length=64), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "provider",
                "provider_transaction_id",
                name="uq_provider_transactions_tenant_provider_txn",
            ),
        )
        op.create_index("ix_provider_transactions_tenant_id", "provider_transactions", ["tenant_id"])
        op.create_index("ix_provider_transactions_provider", "provider_transactions", ["provider"])
        op.create_index("ix_provider_transactions_provider_account_id", "provider_transactions", ["provider_account_id"])
        op.create_index("ix_provider_transactions_provider_transaction_id", "provider_transactions", ["provider_transaction_id"])
        op.create_index("ix_provider_transactions_status", "provider_transactions", ["status"])
        op.create_index("ix_provider_transactions_occurred_at", "provider_transactions", ["occurred_at"])
        _enable_tenant_rls(conn, "provider_transactions")

    if not _has_table(conn, "paypal_webhook_events"):
        op.create_table(
            "paypal_webhook_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("paypal_event_id", sa.String(length=255), nullable=False),
            sa.Column("event_type", sa.String(length=128), nullable=False),
            sa.Column("provider_account_id", sa.String(length=255), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("verification_status", sa.String(length=32), nullable=True),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("process_error", sa.String(length=512), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("paypal_event_id", name="uq_paypal_webhook_events_event_id"),
        )
        op.create_index("ix_paypal_webhook_events_paypal_event_id", "paypal_webhook_events", ["paypal_event_id"])
        op.create_index("ix_paypal_webhook_events_event_type", "paypal_webhook_events", ["event_type"])
        op.create_index("ix_paypal_webhook_events_provider_account_id", "paypal_webhook_events", ["provider_account_id"])

    # payment_attempts provider-neutral extensions
    attempt_cols: list[tuple[str, sa.types.TypeEngine, dict]] = [
        ("tenant_id", sa.Uuid(), {"nullable": True}),
        ("provider", sa.String(length=32), {"nullable": True}),
        ("provider_batch_id", sa.String(length=255), {"nullable": True}),
        ("provider_item_id", sa.String(length=255), {"nullable": True}),
        ("provider_transaction_id", sa.String(length=255), {"nullable": True}),
        ("provider_request_id", sa.String(length=128), {"nullable": True}),
        ("provider_status", sa.String(length=64), {"nullable": True}),
        ("recipient_type", sa.String(length=32), {"nullable": True}),
        ("recipient_value", sa.String(length=255), {"nullable": True}),
        ("submitted_at", sa.DateTime(timezone=True), {"nullable": True}),
        ("completed_at", sa.DateTime(timezone=True), {"nullable": True}),
        ("last_checked_at", sa.DateTime(timezone=True), {"nullable": True}),
    ]
    if _has_table(conn, "payment_attempts"):
        for col, col_type, kwargs in attempt_cols:
            if not _has_column(conn, "payment_attempts", col):
                op.add_column("payment_attempts", sa.Column(col, col_type, **kwargs))
        inspect(conn).clear_cache()
        if _has_column(conn, "payment_attempts", "tenant_id"):
            # Backfill tenant_id from payments where possible
            if conn.dialect.name == "postgresql":
                conn.execute(
                    sa.text(
                        """
                        UPDATE payment_attempts pa
                        SET tenant_id = p.tenant_id
                        FROM payments p
                        WHERE pa.payment_id = p.id
                          AND pa.tenant_id IS NULL
                        """
                    )
                )
            # FK if missing — best-effort via raw SQL for postgres
            if conn.dialect.name == "postgresql":
                conn.execute(
                    sa.text(
                        """
                        DO $$
                        BEGIN
                          IF NOT EXISTS (
                            SELECT 1 FROM information_schema.table_constraints
                            WHERE table_name = 'payment_attempts'
                              AND constraint_name = 'fk_payment_attempts_tenant_id'
                          ) THEN
                            ALTER TABLE payment_attempts
                              ADD CONSTRAINT fk_payment_attempts_tenant_id
                              FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;
                          END IF;
                        END $$;
                        """
                    )
                )
            if not _has_index(conn, "payment_attempts", "ix_payment_attempts_tenant_id"):
                op.create_index("ix_payment_attempts_tenant_id", "payment_attempts", ["tenant_id"])
            _enable_tenant_rls(conn, "payment_attempts")
        for index_name, columns in (
            ("ix_payment_attempts_provider", ["provider"]),
            ("ix_payment_attempts_provider_batch_id", ["provider_batch_id"]),
            ("ix_payment_attempts_provider_item_id", ["provider_item_id"]),
            ("ix_payment_attempts_provider_transaction_id", ["provider_transaction_id"]),
            ("ix_payment_attempts_provider_request_id", ["provider_request_id"]),
        ):
            if all(_has_column(conn, "payment_attempts", c) for c in columns) and not _has_index(
                conn, "payment_attempts", index_name
            ):
                op.create_index(index_name, "payment_attempts", columns)

    # vendor_payment_methods PayPal recipient fields
    vendor_cols: list[tuple[str, sa.types.TypeEngine, dict]] = [
        ("country", sa.String(length=2), {"nullable": True}),
        ("provider", sa.String(length=32), {"nullable": True}),
        ("recipient_type", sa.String(length=32), {"nullable": True}),
        ("recipient_value", sa.String(length=255), {"nullable": True}),
        ("verification_status", sa.String(length=32), {"nullable": True}),
    ]
    if _has_table(conn, "vendor_payment_methods"):
        for col, col_type, kwargs in vendor_cols:
            if not _has_column(conn, "vendor_payment_methods", col):
                op.add_column("vendor_payment_methods", sa.Column(col, col_type, **kwargs))
        inspect(conn).clear_cache()
        if _has_column(conn, "vendor_payment_methods", "provider") and not _has_index(
            conn, "vendor_payment_methods", "ix_vendor_payment_methods_provider"
        ):
            op.create_index("ix_vendor_payment_methods_provider", "vendor_payment_methods", ["provider"])


def downgrade() -> None:
    conn = op.get_bind()

    if _has_table(conn, "vendor_payment_methods"):
        if _has_index(conn, "vendor_payment_methods", "ix_vendor_payment_methods_provider"):
            op.drop_index("ix_vendor_payment_methods_provider", table_name="vendor_payment_methods")
        for col in ("verification_status", "recipient_value", "recipient_type", "provider", "country"):
            if _has_column(conn, "vendor_payment_methods", col):
                op.drop_column("vendor_payment_methods", col)

    if _has_table(conn, "payment_attempts"):
        for index_name in (
            "ix_payment_attempts_provider_request_id",
            "ix_payment_attempts_provider_transaction_id",
            "ix_payment_attempts_provider_item_id",
            "ix_payment_attempts_provider_batch_id",
            "ix_payment_attempts_provider",
            "ix_payment_attempts_tenant_id",
        ):
            if _has_index(conn, "payment_attempts", index_name):
                op.drop_index(index_name, table_name="payment_attempts")
        if conn.dialect.name == "postgresql":
            conn.execute(sa.text('DROP POLICY IF EXISTS tenant_isolation ON "payment_attempts"'))
            conn.execute(
                sa.text(
                    """
                    DO $$
                    BEGIN
                      IF EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE table_name = 'payment_attempts'
                          AND constraint_name = 'fk_payment_attempts_tenant_id'
                      ) THEN
                        ALTER TABLE payment_attempts DROP CONSTRAINT fk_payment_attempts_tenant_id;
                      END IF;
                    END $$;
                    """
                )
            )
        for col in (
            "last_checked_at",
            "completed_at",
            "submitted_at",
            "recipient_value",
            "recipient_type",
            "provider_status",
            "provider_request_id",
            "provider_transaction_id",
            "provider_item_id",
            "provider_batch_id",
            "provider",
            "tenant_id",
        ):
            if _has_column(conn, "payment_attempts", col):
                op.drop_column("payment_attempts", col)

    if _has_table(conn, "paypal_webhook_events"):
        op.drop_table("paypal_webhook_events")

    if _has_table(conn, "provider_transactions"):
        if conn.dialect.name == "postgresql":
            conn.execute(sa.text('DROP POLICY IF EXISTS tenant_isolation ON "provider_transactions"'))
        op.drop_table("provider_transactions")

    if _has_table(conn, "tenant_payment_provider_accounts"):
        if conn.dialect.name == "postgresql":
            conn.execute(sa.text('DROP POLICY IF EXISTS tenant_isolation ON "tenant_payment_provider_accounts"'))
        op.drop_table("tenant_payment_provider_accounts")
