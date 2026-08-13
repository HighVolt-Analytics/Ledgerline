"""Composite indexes for invoice list, matrix, board, and audit hydration.

Revision ID: 091
Revises: 090
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect, text

revision: str = "091"
down_revision: Union[str, None] = "090"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES: tuple[tuple[str, str, str], ...] = (
    (
        "ix_invoices_tenant_created_id",
        "invoices",
        "CREATE INDEX IF NOT EXISTS ix_invoices_tenant_created_id "
        "ON invoices (tenant_id, created_at DESC, id DESC)",
    ),
    (
        "ix_invoices_tenant_status_created",
        "invoices",
        "CREATE INDEX IF NOT EXISTS ix_invoices_tenant_status_created "
        "ON invoices (tenant_id, status, created_at DESC)",
    ),
    (
        "ix_invoices_tenant_route_status",
        "invoices",
        "CREATE INDEX IF NOT EXISTS ix_invoices_tenant_route_status "
        "ON invoices (tenant_id, route_target, status)",
    ),
    (
        "ix_audit_logs_tenant_invoice_created",
        "audit_logs",
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_invoice_created "
        "ON audit_logs (tenant_id, invoice_id, created_at DESC)",
    ),
)


def _index_names(conn, table: str) -> set[str]:
    inspector = inspect(conn)
    if not inspector.has_table(table):
        return set()
    return {idx["name"] for idx in inspector.get_indexes(table) if idx.get("name")}


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name
    for name, table, ddl in _INDEXES:
        if name in _index_names(conn, table):
            continue
        if dialect == "postgresql":
            op.execute(text(ddl))
        elif name == "ix_invoices_tenant_created_id":
            op.create_index(name, table, ["tenant_id", "created_at", "id"])
        elif name == "ix_invoices_tenant_status_created":
            op.create_index(name, table, ["tenant_id", "status", "created_at"])
        elif name == "ix_invoices_tenant_route_status":
            op.create_index(name, table, ["tenant_id", "route_target", "status"])
        elif name == "ix_audit_logs_tenant_invoice_created":
            op.create_index(name, table, ["tenant_id", "invoice_id", "created_at"])


def downgrade() -> None:
    conn = op.get_bind()
    for name, table, _ddl in reversed(_INDEXES):
        if name in _index_names(conn, table):
            op.drop_index(name, table_name=table)
