"""Xero bidirectional master data + sync/export traceability.

Revision ID: 070
Revises: 069
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "070"
down_revision: Union[str, None] = "069"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def _has_table(conn, table: str) -> bool:
    return inspect(conn).has_table(table)


def _has_column(conn, table: str, column: str) -> bool:
    if not _has_table(conn, table):
        return False
    return column in {c["name"] for c in inspect(conn).get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()

    if not _has_table(conn, "xero_accounts"):
        op.create_table(
            "xero_accounts",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("accounting_integration_id", sa.Integer(), nullable=False),
            sa.Column("xero_tenant_id", sa.String(length=128), nullable=False),
            sa.Column("xero_account_id", sa.String(length=128), nullable=False),
            sa.Column("code", sa.String(length=64), nullable=True),
            sa.Column("name", sa.String(length=255), nullable=True),
            sa.Column("account_type", sa.String(length=64), nullable=True),
            sa.Column("account_class", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=True),
            sa.Column("tax_type", sa.String(length=64), nullable=True),
            sa.Column("currency_code", sa.String(length=8), nullable=True),
            sa.Column("enable_payments_to_account", sa.Boolean(), nullable=True),
            sa.Column("show_in_expense_claims", sa.Boolean(), nullable=True),
            sa.Column("description", sa.String(length=512), nullable=True),
            sa.Column("source_system", sa.String(length=32), nullable=False, server_default="xero"),
            sa.Column("sync_status", sa.String(length=32), nullable=False, server_default="active"),
            sa.Column("payload_hash", sa.String(length=64), nullable=True),
            sa.Column("raw_payload_json", sa.Text(), nullable=True),
            sa.Column("last_remote_modified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
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
                "xero_account_id",
                name="uq_xero_accounts_tenant_account",
            ),
        )
        op.create_index("ix_xero_accounts_tenant_id", "xero_accounts", ["tenant_id"])
        op.create_index("ix_xero_accounts_code", "xero_accounts", ["code"])
        op.create_index("ix_xero_accounts_sync_status", "xero_accounts", ["sync_status"])
        _enable_tenant_rls(conn, "xero_accounts")

    if not _has_table(conn, "xero_tax_rates"):
        op.create_table(
            "xero_tax_rates",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("accounting_integration_id", sa.Integer(), nullable=False),
            sa.Column("xero_tenant_id", sa.String(length=128), nullable=False),
            sa.Column("tax_type", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=True),
            sa.Column("effective_rate", sa.Numeric(12, 6), nullable=True),
            sa.Column("display_tax_rate", sa.Numeric(12, 6), nullable=True),
            sa.Column("can_apply_to_assets", sa.Boolean(), nullable=True),
            sa.Column("can_apply_to_equity", sa.Boolean(), nullable=True),
            sa.Column("can_apply_to_expenses", sa.Boolean(), nullable=True),
            sa.Column("can_apply_to_liabilities", sa.Boolean(), nullable=True),
            sa.Column("can_apply_to_revenue", sa.Boolean(), nullable=True),
            sa.Column("source_system", sa.String(length=32), nullable=False, server_default="xero"),
            sa.Column("sync_status", sa.String(length=32), nullable=False, server_default="active"),
            sa.Column("payload_hash", sa.String(length=64), nullable=True),
            sa.Column("raw_payload_json", sa.Text(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
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
                "tax_type",
                name="uq_xero_tax_rates_tenant_tax_type",
            ),
        )
        op.create_index("ix_xero_tax_rates_tenant_id", "xero_tax_rates", ["tenant_id"])
        op.create_index("ix_xero_tax_rates_tax_type", "xero_tax_rates", ["tax_type"])
        _enable_tenant_rls(conn, "xero_tax_rates")

    if not _has_table(conn, "xero_contacts"):
        op.create_table(
            "xero_contacts",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("accounting_integration_id", sa.Integer(), nullable=False),
            sa.Column("xero_tenant_id", sa.String(length=128), nullable=False),
            sa.Column("xero_contact_id", sa.String(length=128), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=True),
            sa.Column("first_name", sa.String(length=128), nullable=True),
            sa.Column("last_name", sa.String(length=128), nullable=True),
            sa.Column("email_address", sa.String(length=255), nullable=True),
            sa.Column("phone", sa.String(length=64), nullable=True),
            sa.Column("contact_status", sa.String(length=32), nullable=True),
            sa.Column("is_supplier", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("is_customer", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("tax_number", sa.String(length=64), nullable=True),
            sa.Column("default_currency", sa.String(length=8), nullable=True),
            sa.Column("accounts_payable_tax_type", sa.String(length=64), nullable=True),
            sa.Column("accounts_receivable_tax_type", sa.String(length=64), nullable=True),
            sa.Column("mapping_status", sa.String(length=32), nullable=False, server_default="unmapped"),
            sa.Column("mapped_vendor_id", sa.Integer(), nullable=True),
            sa.Column("mapped_customer_id", sa.Integer(), nullable=True),
            sa.Column("source_system", sa.String(length=32), nullable=False, server_default="xero"),
            sa.Column("sync_status", sa.String(length=32), nullable=False, server_default="active"),
            sa.Column("payload_hash", sa.String(length=64), nullable=True),
            sa.Column("raw_payload_json", sa.Text(), nullable=True),
            sa.Column("last_remote_modified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
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
                "xero_contact_id",
                name="uq_xero_contacts_tenant_contact",
            ),
        )
        op.create_index("ix_xero_contacts_tenant_id", "xero_contacts", ["tenant_id"])
        op.create_index("ix_xero_contacts_name", "xero_contacts", ["name"])
        op.create_index("ix_xero_contacts_mapping_status", "xero_contacts", ["mapping_status"])
        _enable_tenant_rls(conn, "xero_contacts")

    if not _has_table(conn, "xero_currencies"):
        op.create_table(
            "xero_currencies",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("accounting_integration_id", sa.Integer(), nullable=False),
            sa.Column("xero_tenant_id", sa.String(length=128), nullable=False),
            sa.Column("code", sa.String(length=8), nullable=False),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column("source_system", sa.String(length=32), nullable=False, server_default="xero"),
            sa.Column("sync_status", sa.String(length=32), nullable=False, server_default="active"),
            sa.Column("payload_hash", sa.String(length=64), nullable=True),
            sa.Column("raw_payload_json", sa.Text(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
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
                "code",
                name="uq_xero_currencies_tenant_code",
            ),
        )
        op.create_index("ix_xero_currencies_tenant_id", "xero_currencies", ["tenant_id"])
        _enable_tenant_rls(conn, "xero_currencies")

    # accounting_sync_jobs traceability columns
    for col, col_type, kwargs in (
        ("direction", sa.String(length=16), {"nullable": True}),
        ("entity_type", sa.String(length=32), {"nullable": True}),
        ("records_fetched", sa.Integer(), {"server_default": "0", "nullable": False}),
        ("records_created", sa.Integer(), {"server_default": "0", "nullable": False}),
        ("records_updated", sa.Integer(), {"server_default": "0", "nullable": False}),
        ("records_unchanged", sa.Integer(), {"server_default": "0", "nullable": False}),
        ("records_failed", sa.Integer(), {"server_default": "0", "nullable": False}),
        ("records_persisted", sa.Integer(), {"server_default": "0", "nullable": False}),
        ("correlation_id", sa.String(length=64), {"nullable": True}),
        ("initiated_by", sa.Integer(), {"nullable": True}),
        ("trigger_type", sa.String(length=32), {"nullable": True}),
    ):
        if _has_table(conn, "accounting_sync_jobs") and not _has_column(
            conn, "accounting_sync_jobs", col
        ):
            op.add_column("accounting_sync_jobs", sa.Column(col, col_type, **kwargs))

    for col, col_type, kwargs in (
        ("sync_direction", sa.String(length=16), {"nullable": True}),
        ("source_system", sa.String(length=32), {"nullable": True}),
        ("last_remote_modified_at", sa.DateTime(timezone=True), {"nullable": True}),
        ("last_reconciled_at", sa.DateTime(timezone=True), {"nullable": True}),
        ("reconciliation_status", sa.String(length=32), {"nullable": True}),
        ("amount_due", sa.Numeric(14, 2), {"nullable": True}),
        ("amount_paid", sa.Numeric(14, 2), {"nullable": True}),
        ("is_fully_paid", sa.Boolean(), {"nullable": True}),
    ):
        if not _has_column(conn, "external_accounting_refs", col):
            op.add_column("external_accounting_refs", sa.Column(col, col_type, **kwargs))


def downgrade() -> None:
    conn = op.get_bind()
    for col in (
        "is_fully_paid",
        "amount_paid",
        "amount_due",
        "reconciliation_status",
        "last_reconciled_at",
        "last_remote_modified_at",
        "source_system",
        "sync_direction",
    ):
        if _has_column(conn, "external_accounting_refs", col):
            op.drop_column("external_accounting_refs", col)

    for col in (
        "trigger_type",
        "initiated_by",
        "correlation_id",
        "records_persisted",
        "records_failed",
        "records_unchanged",
        "records_updated",
        "records_created",
        "records_fetched",
        "entity_type",
        "direction",
    ):
        if _has_column(conn, "accounting_sync_jobs", col):
            op.drop_column("accounting_sync_jobs", col)

    for table in ("xero_currencies", "xero_contacts", "xero_tax_rates", "xero_accounts"):
        if _has_table(conn, table):
            if conn.dialect.name == "postgresql":
                conn.execute(sa.text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"'))
            op.drop_table(table)
