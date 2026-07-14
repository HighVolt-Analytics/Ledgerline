"""Fix accounting_sync_jobs schema to match AccountingSyncJob ORM.

Revision ID: 071
Revises: 070

070 declared traceability columns but staging/production may still
lack them (UndefinedColumnError: direction). This migration is idempotent:
add every ORM column / index that is missing, preserve existing rows.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "071"
down_revision: Union[str, None] = "070"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "accounting_sync_jobs"

# Columns present on AccountingSyncJob but not created by 064 (and may be
# missing even when alembic_version reports 065).
_MISSING_COLUMNS: tuple[tuple[str, sa.types.TypeEngine, dict], ...] = (
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
)

# index=True on the ORM (064 only created tenant_id + status).
_INDEXES: tuple[tuple[str, list[str]], ...] = (
    ("ix_accounting_sync_jobs_provider", ["provider"]),
    ("ix_accounting_sync_jobs_job_type", ["job_type"]),
    ("ix_accounting_sync_jobs_direction", ["direction"]),
    ("ix_accounting_sync_jobs_entity_type", ["entity_type"]),
    ("ix_accounting_sync_jobs_correlation_id", ["correlation_id"]),
    ("ix_accounting_sync_jobs_trigger_type", ["trigger_type"]),
)


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


def upgrade() -> None:
    conn = op.get_bind()
    if not _has_table(conn, _TABLE):
        # Table should already exist from 064; recreate baseline + ORM extras
        # only if somehow absent so upgrade remains safe.
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("job_type", sa.String(length=32), nullable=False),
            sa.Column("direction", sa.String(length=16), nullable=True),
            sa.Column("entity_type", sa.String(length=32), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_code", sa.String(length=64), nullable=True),
            sa.Column("error_message", sa.String(length=512), nullable=True),
            sa.Column("payload_hash", sa.String(length=64), nullable=True),
            sa.Column("records_fetched", sa.Integer(), server_default="0", nullable=False),
            sa.Column("records_created", sa.Integer(), server_default="0", nullable=False),
            sa.Column("records_updated", sa.Integer(), server_default="0", nullable=False),
            sa.Column("records_unchanged", sa.Integer(), server_default="0", nullable=False),
            sa.Column("records_failed", sa.Integer(), server_default="0", nullable=False),
            sa.Column("records_persisted", sa.Integer(), server_default="0", nullable=False),
            sa.Column("correlation_id", sa.String(length=64), nullable=True),
            sa.Column("initiated_by", sa.Integer(), nullable=True),
            sa.Column("trigger_type", sa.String(length=32), nullable=True),
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
        op.create_index("ix_accounting_sync_jobs_tenant_id", _TABLE, ["tenant_id"])
        op.create_index("ix_accounting_sync_jobs_status", _TABLE, ["status"])
    else:
        for col, col_type, kwargs in _MISSING_COLUMNS:
            if not _has_column(conn, _TABLE, col):
                op.add_column(_TABLE, sa.Column(col, col_type, **kwargs))
        # DDL can stale the dialect inspector cache used by _has_column/_has_index.
        inspect(conn).clear_cache()

    for index_name, columns in _INDEXES:
        if not _has_index(conn, _TABLE, index_name):
            # Column must exist before index (fresh create path already has cols).
            if all(_has_column(conn, _TABLE, c) for c in columns):
                op.create_index(index_name, _TABLE, columns)


def downgrade() -> None:
    conn = op.get_bind()
    if not _has_table(conn, _TABLE):
        return

    for index_name, _columns in _INDEXES:
        if _has_index(conn, _TABLE, index_name):
            op.drop_index(index_name, table_name=_TABLE)

    # Only drop columns introduced by 065/066 extras — keep 064 baseline.
    for col, _col_type, _kwargs in reversed(_MISSING_COLUMNS):
        if _has_column(conn, _TABLE, col):
            op.drop_column(_TABLE, col)
