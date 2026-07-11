"""Xero refinement — sync jobs, ref reconciliation fields, webhook payload.

Revision ID: 064
Revises: 063
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "064"
down_revision: Union[str, None] = "063"
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


def upgrade() -> None:
    conn = op.get_bind()

    for col, col_type in (
        ("sync_status", sa.String(length=32)),
        ("sync_attempts", sa.Integer()),
        ("sync_error_code", sa.String(length=64)),
        ("sync_error_message", sa.String(length=512)),
    ):
        if not _has_column(conn, "external_accounting_refs", col):
            kwargs: dict = {"nullable": True}
            if col == "sync_attempts":
                kwargs = {"server_default": "0", "nullable": False}
            op.add_column("external_accounting_refs", sa.Column(col, col_type, **kwargs))

    if not _has_column(conn, "xero_webhook_events", "payload_json"):
        op.add_column("xero_webhook_events", sa.Column("payload_json", sa.Text(), nullable=True))
    if not _has_column(conn, "xero_webhook_events", "signature_valid"):
        op.add_column(
            "xero_webhook_events",
            sa.Column("signature_valid", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        )

    if not inspect(conn).has_table("accounting_sync_jobs"):
        op.create_table(
            "accounting_sync_jobs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("job_type", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_code", sa.String(length=64), nullable=True),
            sa.Column("error_message", sa.String(length=512), nullable=True),
            sa.Column("payload_hash", sa.String(length=64), nullable=True),
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
        op.create_index("ix_accounting_sync_jobs_tenant_id", "accounting_sync_jobs", ["tenant_id"])
        op.create_index("ix_accounting_sync_jobs_status", "accounting_sync_jobs", ["status"])
        _enable_tenant_rls(conn, "accounting_sync_jobs")


def _has_column(conn, table: str, column: str) -> bool:
    if not inspect(conn).has_table(table):
        return False
    return column in {c["name"] for c in inspect(conn).get_columns(table)}


def downgrade() -> None:
    conn = op.get_bind()
    if inspect(conn).has_table("accounting_sync_jobs"):
        if conn.dialect.name == "postgresql":
            conn.execute(sa.text('DROP POLICY IF EXISTS tenant_isolation ON "accounting_sync_jobs"'))
        op.drop_table("accounting_sync_jobs")
    for col in ("sync_error_message", "sync_error_code", "sync_attempts", "sync_status"):
        if _has_column(conn, "external_accounting_refs", col):
            op.drop_column("external_accounting_refs", col)
    for col in ("signature_valid", "payload_json"):
        if _has_column(conn, "xero_webhook_events", col):
            op.drop_column("xero_webhook_events", col)
