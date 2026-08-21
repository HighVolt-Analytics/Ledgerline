"""Composite index for tenant-scoped audit log recency (dashboard notifications/activity).

Revision ID: 095
Revises: 094

Invoice (tenant_id, created_at) indexes already ship in 091. Notifications and
activity order by audit_logs.created_at for one tenant; the existing
(tenant_id, invoice_id, created_at) index does not cover that access path.
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect, text

revision: str = "095"
down_revision: Union[str, None] = "094"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "ix_audit_logs_tenant_created"
_TABLE = "audit_logs"
_PG_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_created "
    "ON audit_logs (tenant_id, created_at DESC)"
)


def _index_names(conn, table: str) -> set[str]:
    inspector = inspect(conn)
    if not inspector.has_table(table):
        return set()
    return {idx["name"] for idx in inspector.get_indexes(table) if idx.get("name")}


def upgrade() -> None:
    conn = op.get_bind()
    if _INDEX_NAME in _index_names(conn, _TABLE):
        return
    if conn.dialect.name == "postgresql":
        op.execute(text(_PG_DDL))
        return
    op.create_index(_INDEX_NAME, _TABLE, ["tenant_id", "created_at"])


def downgrade() -> None:
    conn = op.get_bind()
    if _INDEX_NAME in _index_names(conn, _TABLE):
        op.drop_index(_INDEX_NAME, table_name=_TABLE)
