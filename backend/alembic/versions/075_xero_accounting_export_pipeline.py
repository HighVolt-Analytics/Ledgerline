"""Xero accounting export pipeline: mappings, ledger, tracking, org profile.

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

_RLS_TABLES = (
    "accounting_entity_mappings",
    "accounting_export_ledger",
    "xero_tracking_categories",
    "xero_organisation_profiles",
)


def _has_table(conn, table: str) -> bool:
    return inspect(conn).has_table(table)


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

    if not _has_table(conn, "accounting_entity_mappings"):
        op.create_table(
            "accounting_entity_mappings",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("mapping_type", sa.String(length=32), nullable=False),
            sa.Column("source_key", sa.String(length=255), nullable=False),
            sa.Column("source_label", sa.String(length=255), nullable=True),
            sa.Column("external_id", sa.String(length=128), nullable=True),
            sa.Column("external_code", sa.String(length=128), nullable=True),
            sa.Column("external_name", sa.String(length=255), nullable=True),
            sa.Column("external_option_id", sa.String(length=128), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("updated_by", sa.Integer(), nullable=True),
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
                "tenant_id",
                "provider",
                "mapping_type",
                "source_key",
                name="uq_accounting_entity_mappings_source",
            ),
        )
        op.create_index(
            "ix_accounting_entity_mappings_tenant_id",
            "accounting_entity_mappings",
            ["tenant_id"],
        )
        op.create_index(
            "ix_accounting_entity_mappings_provider",
            "accounting_entity_mappings",
            ["provider"],
        )
        op.create_index(
            "ix_accounting_entity_mappings_type",
            "accounting_entity_mappings",
            ["mapping_type"],
        )

    if not _has_table(conn, "accounting_export_ledger"):
        op.create_table(
            "accounting_export_ledger",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("qll_transaction_id", sa.String(length=64), nullable=False),
            sa.Column("source_invoice_id", sa.Integer(), nullable=False),
            sa.Column("source_document_id", sa.String(length=64), nullable=True),
            sa.Column("transaction_type", sa.String(length=32), nullable=False),
            sa.Column("direction", sa.String(length=16), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("payload_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.Column("idempotency_key", sa.String(length=128), nullable=False),
            sa.Column("canonical_json", sa.Text(), nullable=True),
            sa.Column("request_payload_json", sa.Text(), nullable=True),
            sa.Column("external_id", sa.String(length=128), nullable=True),
            sa.Column("external_number", sa.String(length=128), nullable=True),
            sa.Column("external_status", sa.String(length=64), nullable=True),
            sa.Column("external_contact_id", sa.String(length=128), nullable=True),
            sa.Column("external_currency", sa.String(length=8), nullable=True),
            sa.Column("external_total", sa.Numeric(14, 2), nullable=True),
            sa.Column("xero_tenant_id", sa.String(length=128), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_bucket", sa.String(length=32), nullable=True),
            sa.Column("error_code", sa.String(length=64), nullable=True),
            sa.Column("error_message", sa.String(length=512), nullable=True),
            sa.Column("request_correlation_id", sa.String(length=64), nullable=True),
            sa.Column("last_response_summary", sa.Text(), nullable=True),
            sa.Column("attachment_status", sa.String(length=32), nullable=True),
            sa.Column("attachment_external_id", sa.String(length=128), nullable=True),
            sa.Column("attachment_error", sa.String(length=512), nullable=True),
            sa.Column("divergence_flags_json", sa.Text(), nullable=True),
            sa.Column("amount_due", sa.Numeric(14, 2), nullable=True),
            sa.Column("amount_paid", sa.Numeric(14, 2), nullable=True),
            sa.Column("is_fully_paid", sa.Boolean(), nullable=True),
            sa.Column("last_remote_modified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
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
                ["source_invoice_id"],
                ["invoices.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "provider",
                "qll_transaction_id",
                "payload_version",
                name="uq_accounting_export_ledger_txn_version",
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "provider",
                "idempotency_key",
                name="uq_accounting_export_ledger_idempotency",
            ),
        )
        op.create_index(
            "ix_accounting_export_ledger_tenant_id",
            "accounting_export_ledger",
            ["tenant_id"],
        )
        op.create_index(
            "ix_accounting_export_ledger_status",
            "accounting_export_ledger",
            ["status"],
        )
        op.create_index(
            "ix_accounting_export_ledger_invoice",
            "accounting_export_ledger",
            ["source_invoice_id"],
        )
        op.create_index(
            "ix_accounting_export_ledger_external_id",
            "accounting_export_ledger",
            ["external_id"],
        )

    if not _has_table(conn, "xero_tracking_categories"):
        op.create_table(
            "xero_tracking_categories",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("accounting_integration_id", sa.Integer(), nullable=False),
            sa.Column("xero_tenant_id", sa.String(length=128), nullable=False),
            sa.Column("xero_tracking_category_id", sa.String(length=128), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=True),
            sa.Column("option_external_id", sa.String(length=128), nullable=True),
            sa.Column("option_name", sa.String(length=255), nullable=True),
            sa.Column("option_status", sa.String(length=32), nullable=True),
            sa.Column("source_system", sa.String(length=32), nullable=False, server_default="xero"),
            sa.Column("sync_status", sa.String(length=32), nullable=False, server_default="active"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("payload_hash", sa.String(length=64), nullable=True),
            sa.Column("raw_payload_json", sa.Text(), nullable=True),
            sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
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
                ["accounting_integration_id"],
                ["accounting_integrations.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "xero_tenant_id",
                "xero_tracking_category_id",
                "option_external_id",
                name="uq_xero_tracking_categories_option",
            ),
        )
        op.create_index(
            "ix_xero_tracking_categories_tenant_id",
            "xero_tracking_categories",
            ["tenant_id"],
        )

    if not _has_table(conn, "xero_organisation_profiles"):
        op.create_table(
            "xero_organisation_profiles",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("accounting_integration_id", sa.Integer(), nullable=False),
            sa.Column("xero_tenant_id", sa.String(length=128), nullable=False),
            sa.Column("organisation_id", sa.String(length=128), nullable=True),
            sa.Column("name", sa.String(length=255), nullable=True),
            sa.Column("legal_name", sa.String(length=255), nullable=True),
            sa.Column("base_currency", sa.String(length=8), nullable=True),
            sa.Column("country_code", sa.String(length=8), nullable=True),
            sa.Column("organisation_status", sa.String(length=64), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("payload_hash", sa.String(length=64), nullable=True),
            sa.Column("raw_payload_json", sa.Text(), nullable=True),
            sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
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
                ["accounting_integration_id"],
                ["accounting_integrations.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "xero_tenant_id",
                name="uq_xero_organisation_profiles_tenant_org",
            ),
        )
        op.create_index(
            "ix_xero_organisation_profiles_tenant_id",
            "xero_organisation_profiles",
            ["tenant_id"],
        )

    for table in _RLS_TABLES:
        if _has_table(conn, table):
            _enable_rls(conn, table)


def downgrade() -> None:
    conn = op.get_bind()
    for table in reversed(_RLS_TABLES):
        if _has_table(conn, table):
            _disable_rls(conn, table)
            op.drop_table(table)
