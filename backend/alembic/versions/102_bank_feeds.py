"""Bank feeds / cash reconciliation tables + audit_logs.detail GIN index.

Revision ID: 102
Revises: 101

New domain (bank_accounts, bank_feed_imports, bank_transactions,
bank_transaction_matches) is separate from daily_reconciliations and Xero
reconciliation. Also adds a GIN index on audit_logs.detail so bank feed
events keyed by bank_transaction_id / import_id in JSONB can be queried
without a schema change to audit_logs.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "102"
down_revision: Union[str, None] = "101"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def upgrade() -> None:
    json_type = sa.JSON().with_variant(JSONB(astext_type=sa.Text()), "postgresql")

    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("account_mask", sa.String(length=32), nullable=True),
        sa.Column("coa_account_code", sa.String(length=64), nullable=False),
        sa.Column("coa_account_name", sa.String(length=255), nullable=False),
        sa.Column("connection_type", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("external_item_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
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
    )
    op.create_index("ix_bank_accounts_tenant_id", "bank_accounts", ["tenant_id"])
    op.create_index("ix_bank_accounts_status", "bank_accounts", ["status"])

    op.create_table(
        "bank_feed_imports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("bank_account_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="csv"),
        sa.Column("filename", sa.String(length=512), nullable=True),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_report", json_type, nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["bank_account_id"], ["bank_accounts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "bank_account_id",
            "file_sha256",
            name="uq_bank_feed_imports_file_sha256",
        ),
    )
    op.create_index("ix_bank_feed_imports_tenant_id", "bank_feed_imports", ["tenant_id"])
    op.create_index(
        "ix_bank_feed_imports_bank_account_id",
        "bank_feed_imports",
        ["bank_account_id"],
    )

    op.create_table(
        "bank_transactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("bank_account_id", sa.Integer(), nullable=False),
        sa.Column("import_id", sa.Integer(), nullable=True),
        sa.Column("txn_date", sa.Date(), nullable=False),
        sa.Column("posted_date", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("description_normalized", sa.Text(), nullable=False, server_default=""),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("balance", sa.Numeric(14, 2), nullable=True),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "match_status",
            sa.String(length=32),
            nullable=False,
            server_default="unmatched",
        ),
        sa.Column("category_coa", sa.String(length=255), nullable=True),
        sa.Column("review_flags", json_type, nullable=True),
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
        sa.ForeignKeyConstraint(
            ["bank_account_id"], ["bank_accounts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["import_id"], ["bank_feed_imports.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "bank_account_id",
            "fingerprint",
            name="uq_bank_transactions_fingerprint",
        ),
    )
    op.create_index("ix_bank_transactions_tenant_id", "bank_transactions", ["tenant_id"])
    op.create_index(
        "ix_bank_transactions_bank_account_id",
        "bank_transactions",
        ["bank_account_id"],
    )
    op.create_index(
        "ix_bank_transactions_match_status",
        "bank_transactions",
        ["tenant_id", "match_status"],
    )
    op.create_index(
        "ix_bank_transactions_txn_date",
        "bank_transactions",
        ["tenant_id", "txn_date"],
    )
    op.create_index(
        "uq_bank_transactions_external_id",
        "bank_transactions",
        ["tenant_id", "bank_account_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
        sqlite_where=sa.text("external_id IS NOT NULL"),
    )

    op.create_table(
        "bank_transaction_matches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("bank_transaction_id", sa.Integer(), nullable=False),
        sa.Column("matched_type", sa.String(length=32), nullable=False),
        sa.Column("matched_id", sa.Integer(), nullable=False),
        sa.Column("allocated_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("match_confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("match_method", sa.String(length=32), nullable=False),
        sa.Column("match_reasons", json_type, nullable=True),
        sa.Column("matched_by", sa.String(length=255), nullable=True),
        sa.Column(
            "matched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("unmatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unmatch_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["bank_transaction_id"],
            ["bank_transactions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bank_transaction_matches_tenant_id",
        "bank_transaction_matches",
        ["tenant_id"],
    )
    op.create_index(
        "ix_bank_transaction_matches_txn_id",
        "bank_transaction_matches",
        ["bank_transaction_id"],
    )
    op.create_index(
        "ix_bank_transaction_matches_entity",
        "bank_transaction_matches",
        ["tenant_id", "matched_type", "matched_id"],
    )
    op.create_index(
        "ix_bank_transaction_matches_active",
        "bank_transaction_matches",
        ["bank_transaction_id"],
        postgresql_where=sa.text("unmatched_at IS NULL"),
        sqlite_where=sa.text("unmatched_at IS NULL"),
    )

    conn = op.get_bind()
    for table in (
        "bank_accounts",
        "bank_feed_imports",
        "bank_transactions",
        "bank_transaction_matches",
    ):
        _enable_rls(conn, table)

    # Containment queries: detail @> '{"bank_transaction_id": N}' / import_id
    if conn.dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                CREATE INDEX IF NOT EXISTS ix_audit_logs_detail_gin
                ON audit_logs
                USING GIN (detail jsonb_path_ops)
                """
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute(sa.text("DROP INDEX IF EXISTS ix_audit_logs_detail_gin"))

    for table in (
        "bank_transaction_matches",
        "bank_transactions",
        "bank_feed_imports",
        "bank_accounts",
    ):
        _disable_rls(conn, table)

    op.drop_index(
        "ix_bank_transaction_matches_active",
        table_name="bank_transaction_matches",
    )
    op.drop_index(
        "ix_bank_transaction_matches_entity",
        table_name="bank_transaction_matches",
    )
    op.drop_index(
        "ix_bank_transaction_matches_txn_id",
        table_name="bank_transaction_matches",
    )
    op.drop_index(
        "ix_bank_transaction_matches_tenant_id",
        table_name="bank_transaction_matches",
    )
    op.drop_table("bank_transaction_matches")

    op.drop_index("uq_bank_transactions_external_id", table_name="bank_transactions")
    op.drop_index("ix_bank_transactions_txn_date", table_name="bank_transactions")
    op.drop_index("ix_bank_transactions_match_status", table_name="bank_transactions")
    op.drop_index(
        "ix_bank_transactions_bank_account_id", table_name="bank_transactions"
    )
    op.drop_index("ix_bank_transactions_tenant_id", table_name="bank_transactions")
    op.drop_table("bank_transactions")

    op.drop_index(
        "ix_bank_feed_imports_bank_account_id", table_name="bank_feed_imports"
    )
    op.drop_index("ix_bank_feed_imports_tenant_id", table_name="bank_feed_imports")
    op.drop_table("bank_feed_imports")

    op.drop_index("ix_bank_accounts_status", table_name="bank_accounts")
    op.drop_index("ix_bank_accounts_tenant_id", table_name="bank_accounts")
    op.drop_table("bank_accounts")
