"""Add journal_batches, batch_id on journal_entries, and DB-enforced balance.

Closes the gap where journal_generator.is_balanced() was only checked by
callers before persist_journal_lines() — never enforced by the database
itself, so any other insert path could write unbalanced lines. Every
journal_entries row now belongs to exactly one journal_batch, and a deferred
constraint trigger sums debit/credit per batch at commit and rejects the
transaction if they don't match.

Revision ID: 100
Revises: 099
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "100"
down_revision: Union[str, None] = "099"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _enable_rls(conn, table: str) -> None:
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


def upgrade() -> None:
    conn = op.get_bind()

    # Reuse the existing Postgres enum from migration 064 — sa.Enum(create_type=False)
    # is not enough under asyncpg (SQLAlchemy still emits CREATE TYPE). Use the
    # dialect ENUM with create_type=False and do not call .create().
    journal_entry_kind = postgresql.ENUM(
        "invoice_accrual",
        "payment_settlement",
        "collection_settlement",
        name="journal_entry_kind",
        create_type=False,
    )

    op.create_table(
        "journal_batches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "invoice_id",
            sa.Integer(),
            sa.ForeignKey("invoices.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "entry_kind",
            journal_entry_kind,
            nullable=False,
            server_default="invoice_accrual",
        ),
        sa.Column(
            "payment_id",
            sa.Integer(),
            sa.ForeignKey("payments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "collection_id",
            sa.Integer(),
            sa.ForeignKey("collections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="posted"),
        sa.Column("reversed_by_batch_id", sa.Integer(), nullable=True),
        sa.Column("reversal_reason", sa.String(length=255), nullable=True),
        sa.Column(
            "posted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_journal_batches_reversed_by",
        "journal_batches",
        "journal_batches",
        ["reversed_by_batch_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_journal_batches_tenant_id", "journal_batches", ["tenant_id"])
    op.create_index("ix_journal_batches_invoice_id", "journal_batches", ["invoice_id"])
    op.create_index("ix_journal_batches_entry_kind", "journal_batches", ["entry_kind"])
    op.create_index("ix_journal_batches_payment_id", "journal_batches", ["payment_id"])
    op.create_index(
        "ix_journal_batches_collection_id", "journal_batches", ["collection_id"]
    )
    op.create_index("ix_journal_batches_status", "journal_batches", ["status"])

    _enable_rls(conn, "journal_batches")

    # --- batch_id on journal_entries -------------------------------------
    op.add_column("journal_entries", sa.Column("batch_id", sa.Integer(), nullable=True))

    # Backfill: one batch per distinct (tenant, invoice, kind, payment,
    # collection) group of *existing* rows. Safe because the pre-existing
    # delete+rewrite behavior (remap/reset/purge) already guaranteed at most
    # one live set of rows per that grouping at any point in time — there is
    # no history to preserve pre-migration, only current state.
    conn.execute(
        sa.text(
            """
            INSERT INTO journal_batches
                (tenant_id, invoice_id, entry_kind, payment_id, collection_id, status, posted_at)
            SELECT tenant_id, invoice_id, entry_kind, payment_id, collection_id, 'posted', now()
            FROM journal_entries
            GROUP BY tenant_id, invoice_id, entry_kind, payment_id, collection_id
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE journal_entries je
            SET batch_id = jb.id
            FROM journal_batches jb
            WHERE je.tenant_id = jb.tenant_id
              AND je.invoice_id = jb.invoice_id
              AND je.entry_kind = jb.entry_kind
              AND je.payment_id IS NOT DISTINCT FROM jb.payment_id
              AND je.collection_id IS NOT DISTINCT FROM jb.collection_id
              AND je.batch_id IS NULL
            """
        )
    )

    # Pre-flight: abort with actionable detail rather than let the balance
    # trigger (added below) fail mysteriously on legacy bad data.
    conn.execute(
        sa.text(
            """
            DO $$
            DECLARE
                bad_count integer;
            BEGIN
                SELECT COUNT(*) INTO bad_count FROM (
                    SELECT batch_id
                    FROM journal_entries
                    GROUP BY batch_id
                    HAVING SUM(debit) <> SUM(credit)
                ) unbalanced;
                IF bad_count > 0 THEN
                    RAISE EXCEPTION
                        'migration 099: % existing journal batch(es) do not balance — fix before enabling the DB constraint',
                        bad_count;
                END IF;
            END $$;
            """
        )
    )

    op.alter_column("journal_entries", "batch_id", nullable=False)
    op.create_foreign_key(
        "fk_journal_entries_batch_id",
        "journal_entries",
        "journal_batches",
        ["batch_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_journal_entries_batch_id", "journal_entries", ["batch_id"])

    # Single-row guard: non-negative, exactly one side populated per line.
    op.create_check_constraint(
        "ck_journal_entries_debit_credit_sides",
        "journal_entries",
        "(debit >= 0 AND credit >= 0) AND (debit = 0 OR credit = 0)",
    )

    # Cross-row guard: debits == credits per batch, enforced at commit so it
    # catches every insert path, not just persist_journal_lines().
    conn.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION check_journal_batch_balanced() RETURNS trigger AS $$
            DECLARE
                target_batch_id integer;
                total_debit numeric(14,2);
                total_credit numeric(14,2);
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    target_batch_id := OLD.batch_id;
                ELSE
                    target_batch_id := NEW.batch_id;
                END IF;

                SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0)
                INTO total_debit, total_credit
                FROM journal_entries
                WHERE batch_id = target_batch_id;

                IF total_debit <> total_credit THEN
                    RAISE EXCEPTION
                        'journal_batch %: debits (%) do not equal credits (%)',
                        target_batch_id, total_debit, total_credit
                        USING ERRCODE = '23514';
                END IF;
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    conn.execute(
        sa.text('DROP TRIGGER IF EXISTS trg_journal_batch_balanced ON "journal_entries"')
    )
    conn.execute(
        sa.text(
            """
            CREATE CONSTRAINT TRIGGER trg_journal_batch_balanced
            AFTER INSERT OR UPDATE OR DELETE ON journal_entries
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW
            EXECUTE FUNCTION check_journal_batch_balanced();
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text('DROP TRIGGER IF EXISTS trg_journal_batch_balanced ON "journal_entries"')
    )
    conn.execute(sa.text("DROP FUNCTION IF EXISTS check_journal_batch_balanced()"))
    op.drop_constraint(
        "ck_journal_entries_debit_credit_sides", "journal_entries", type_="check"
    )
    op.drop_constraint("fk_journal_entries_batch_id", "journal_entries", type_="foreignkey")
    op.drop_index("ix_journal_entries_batch_id", table_name="journal_entries")
    op.drop_column("journal_entries", "batch_id")
    conn.execute(sa.text('DROP POLICY IF EXISTS tenant_isolation ON "journal_batches"'))
    op.drop_table("journal_batches")
