"""Xero production integration — connections, external refs, integration metadata.

Revision ID: 068
Revises: 067
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "068"
down_revision: Union[str, None] = "067"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(conn, table: str, column: str) -> bool:
    if not inspect(conn).has_table(table):
        return False
    return column in {c["name"] for c in inspect(conn).get_columns(table)}


def _has_index(conn, table: str, index_name: str) -> bool:
    if not inspect(conn).has_table(table):
        return False
    return index_name in {idx["name"] for idx in inspect(conn).get_indexes(table)}


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


def upgrade() -> None:
    conn = op.get_bind()

    for col, col_type, kwargs in (
        ("xero_connection_id", sa.String(length=128), {"nullable": True}),
        ("provider_tenant_type", sa.String(length=64), {"nullable": True}),
        ("token_version", sa.Integer(), {"server_default": "0", "nullable": False}),
        ("last_refresh_at", sa.DateTime(timezone=True), {"nullable": True}),
        ("last_successful_sync_at", sa.DateTime(timezone=True), {"nullable": True}),
        ("last_error_code", sa.String(length=64), {"nullable": True}),
    ):
        if not _has_column(conn, "accounting_integrations", col):
            op.add_column("accounting_integrations", sa.Column(col, col_type, **kwargs))

    if not _has_index(conn, "accounting_integrations", "ix_accounting_integrations_xero_connection_id"):
        op.create_index(
            "ix_accounting_integrations_xero_connection_id",
            "accounting_integrations",
            ["xero_connection_id"],
        )

    if not inspect(conn).has_table("xero_connections"):
        op.create_table(
            "xero_connections",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("accounting_integration_id", sa.Integer(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("xero_connection_id", sa.String(length=128), nullable=False),
            sa.Column("xero_tenant_id", sa.String(length=128), nullable=False),
            sa.Column("xero_tenant_type", sa.String(length=64), nullable=True),
            sa.Column("xero_tenant_name", sa.String(length=255), nullable=True),
            sa.Column("selected", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
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
            sa.ForeignKeyConstraint(
                ["accounting_integration_id"],
                ["accounting_integrations.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "accounting_integration_id",
                "xero_connection_id",
                name="uq_xero_connections_integration_connection",
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "xero_tenant_id",
                name="uq_xero_connections_tenant_xero_tenant",
            ),
        )
        op.create_index("ix_xero_connections_tenant_id", "xero_connections", ["tenant_id"])
        op.create_index(
            "ix_xero_connections_accounting_integration_id",
            "xero_connections",
            ["accounting_integration_id"],
        )
        _enable_tenant_rls(conn, "xero_connections")

    if not inspect(conn).has_table("external_accounting_refs"):
        op.create_table(
            "external_accounting_refs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("entity_type", sa.String(length=32), nullable=False),
            sa.Column("internal_entity_id", sa.String(length=255), nullable=False),
            sa.Column("external_entity_id", sa.String(length=128), nullable=False),
            sa.Column("external_number", sa.String(length=128), nullable=True),
            sa.Column("external_status", sa.String(length=64), nullable=True),
            sa.Column("payload_hash", sa.String(length=64), nullable=True),
            sa.Column("last_pushed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error_code", sa.String(length=64), nullable=True),
            sa.Column("last_error_message", sa.String(length=512), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
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
                "entity_type",
                "internal_entity_id",
                name="uq_external_accounting_refs_internal",
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "provider",
                "entity_type",
                "external_entity_id",
                name="uq_external_accounting_refs_external",
            ),
        )
        op.create_index("ix_external_accounting_refs_tenant_id", "external_accounting_refs", ["tenant_id"])
        op.create_index(
            "ix_external_accounting_refs_payload_hash",
            "external_accounting_refs",
            ["payload_hash"],
        )
        _enable_tenant_rls(conn, "external_accounting_refs")

    if not inspect(conn).has_table("xero_webhook_events"):
        op.create_table(
            "xero_webhook_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("event_key", sa.String(length=255), nullable=False),
            sa.Column("xero_tenant_id", sa.String(length=128), nullable=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=True),
            sa.Column("event_category", sa.String(length=64), nullable=True),
            sa.Column("event_type", sa.String(length=64), nullable=True),
            sa.Column(
                "received_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("event_key", name="uq_xero_webhook_events_event_key"),
        )
        op.create_index("ix_xero_webhook_events_xero_tenant_id", "xero_webhook_events", ["xero_tenant_id"])


def downgrade() -> None:
    conn = op.get_bind()
    if inspect(conn).has_table("xero_webhook_events"):
        op.drop_table("xero_webhook_events")
    if conn.dialect.name == "postgresql":
        for table in ("external_accounting_refs", "xero_connections"):
            if inspect(conn).has_table(table):
                conn.execute(sa.text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"'))
    if inspect(conn).has_table("external_accounting_refs"):
        op.drop_table("external_accounting_refs")
    if inspect(conn).has_table("xero_connections"):
        op.drop_table("xero_connections")
    if _has_index(conn, "accounting_integrations", "ix_accounting_integrations_xero_connection_id"):
        op.drop_index("ix_accounting_integrations_xero_connection_id", table_name="accounting_integrations")
    for col in (
        "last_error_code",
        "last_successful_sync_at",
        "last_refresh_at",
        "token_version",
        "provider_tenant_type",
        "xero_connection_id",
    ):
        if _has_column(conn, "accounting_integrations", col):
            op.drop_column("accounting_integrations", col)
