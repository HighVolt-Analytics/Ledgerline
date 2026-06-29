"""LLM classification learning loop + OCR artifact cache with tenant RLS.

Revision ID: 044
Revises: 043
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "044"
down_revision: Union[str, None] = "043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_TABLES = ("invoice_ocr_artifacts", "classification_learning_events")


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

    op.create_table(
        "invoice_ocr_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("di_model", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("text_excerpt", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invoice_ocr_artifacts_tenant_id", "invoice_ocr_artifacts", ["tenant_id"])
    op.create_index("ix_invoice_ocr_artifacts_invoice_id", "invoice_ocr_artifacts", ["invoice_id"])
    op.create_index("ix_invoice_ocr_artifacts_file_hash", "invoice_ocr_artifacts", ["file_hash"])

    op.create_table(
        "classification_learning_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=True),
        sa.Column("ocr_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("llm_suggested_dt", sa.String(length=16), nullable=True),
        sa.Column("llm_confidence", sa.Float(), nullable=True),
        sa.Column("policy_winner_dt", sa.String(length=16), nullable=True),
        sa.Column("human_confirmed_dt", sa.String(length=16), nullable=True),
        sa.Column("review_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("llm_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reviewer_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ocr_artifact_id"], ["invoice_ocr_artifacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_classification_learning_events_tenant_id",
        "classification_learning_events",
        ["tenant_id"],
    )
    op.create_index(
        "ix_classification_learning_events_invoice_id",
        "classification_learning_events",
        ["invoice_id"],
    )
    op.create_index(
        "ix_classification_learning_events_file_hash",
        "classification_learning_events",
        ["file_hash"],
    )

    op.add_column("invoices", sa.Column("llm_suggested_dt", sa.String(length=16), nullable=True))
    op.add_column("invoices", sa.Column("llm_confidence", sa.Float(), nullable=True))

    for table in _RLS_TABLES:
        _enable_rls(conn, table)


def downgrade() -> None:
    conn = op.get_bind()
    for table in _RLS_TABLES:
        conn.execute(sa.text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"'))
        conn.execute(sa.text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))

    op.drop_column("invoices", "llm_confidence")
    op.drop_column("invoices", "llm_suggested_dt")
    op.drop_table("classification_learning_events")
    op.drop_table("invoice_ocr_artifacts")
