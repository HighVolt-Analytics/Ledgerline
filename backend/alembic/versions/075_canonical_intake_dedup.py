"""Canonical intake: normalized filename, review flag, page fingerprints.

Revision ID: 075
Revises: 074
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "075"
down_revision: Union[str, None] = "074"
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
    conn = op.get_bind()

    if not _has_column(conn, "invoices", "normalized_filename"):
        op.add_column(
            "invoices",
            sa.Column("normalized_filename", sa.String(length=255), nullable=True),
        )
    if not _has_column(conn, "invoices", "duplicate_review_suggested"):
        op.add_column(
            "invoices",
            sa.Column(
                "duplicate_review_suggested",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if not _has_index(conn, "invoices", "ix_invoices_tenant_normalized_filename"):
        op.create_index(
            "ix_invoices_tenant_normalized_filename",
            "invoices",
            ["tenant_id", "normalized_filename"],
        )

    if not _has_table(conn, "invoice_page_fingerprints"):
        op.create_table(
            "invoice_page_fingerprints",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("invoice_id", sa.Integer(), nullable=False),
            sa.Column("page_index", sa.Integer(), nullable=False),
            sa.Column("page_fingerprint", sa.String(length=64), nullable=False),
            sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "invoice_id",
                "page_index",
                name="uq_invoice_page_fingerprints_invoice_page",
            ),
        )
    if not _has_index(conn, "invoice_page_fingerprints", "ix_invoice_page_fingerprints_tenant_fp"):
        op.create_index(
            "ix_invoice_page_fingerprints_tenant_fp",
            "invoice_page_fingerprints",
            ["tenant_id", "page_fingerprint"],
        )
    if not _has_index(conn, "invoice_page_fingerprints", "ix_invoice_page_fingerprints_invoice_id"):
        op.create_index(
            "ix_invoice_page_fingerprints_invoice_id",
            "invoice_page_fingerprints",
            ["invoice_id"],
        )

    _enable_rls(conn, "invoice_page_fingerprints")


def downgrade() -> None:
    conn = op.get_bind()
    _disable_rls(conn, "invoice_page_fingerprints")
    if _has_index(conn, "invoice_page_fingerprints", "ix_invoice_page_fingerprints_invoice_id"):
        op.drop_index(
            "ix_invoice_page_fingerprints_invoice_id",
            table_name="invoice_page_fingerprints",
        )
    if _has_index(conn, "invoice_page_fingerprints", "ix_invoice_page_fingerprints_tenant_fp"):
        op.drop_index(
            "ix_invoice_page_fingerprints_tenant_fp",
            table_name="invoice_page_fingerprints",
        )
    if _has_table(conn, "invoice_page_fingerprints"):
        op.drop_table("invoice_page_fingerprints")
    if _has_index(conn, "invoices", "ix_invoices_tenant_normalized_filename"):
        op.drop_index("ix_invoices_tenant_normalized_filename", table_name="invoices")
    if _has_column(conn, "invoices", "duplicate_review_suggested"):
        op.drop_column("invoices", "duplicate_review_suggested")
    if _has_column(conn, "invoices", "normalized_filename"):
        op.drop_column("invoices", "normalized_filename")
