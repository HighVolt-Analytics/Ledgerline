"""Platform prompt versions tables + seed v1 from code catalog.

Revision ID: 077
Revises: 076
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "077"
down_revision: Union[str, None] = "076"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(conn, table: str) -> bool:
    return inspect(conn).has_table(table)


def _has_index(conn, table: str, index_name: str) -> bool:
    if not _has_table(conn, table):
        return False
    return index_name in {idx["name"] for idx in inspect(conn).get_indexes(table)}


def upgrade() -> None:
    conn = op.get_bind()

    if not _has_table(conn, "platform_prompt_versions"):
        op.create_table(
            "platform_prompt_versions",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("prompt_key", sa.String(length=128), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("prompt_key", "version", name="uq_platform_prompt_key_version"),
        )
    if not _has_index(conn, "platform_prompt_versions", "ix_platform_prompt_versions_prompt_key"):
        op.create_index(
            "ix_platform_prompt_versions_prompt_key",
            "platform_prompt_versions",
            ["prompt_key"],
        )

    if not _has_table(conn, "platform_prompt_active"):
        op.create_table(
            "platform_prompt_active",
            sa.Column("prompt_key", sa.String(length=128), nullable=False),
            sa.Column("active_version_id", sa.Integer(), nullable=False),
            sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["active_version_id"],
                ["platform_prompt_versions.id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("prompt_key"),
        )

    # Seed v1 from code catalog (idempotent: only when table empty for that key).
    # Load catalog.py by path so package __init__ (and its model imports) are not required
    # during migrate-only deploys that have the migration files but not the full app surface.
    import importlib.util
    import sys
    from pathlib import Path

    catalog_path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "services"
        / "prompt_registry"
        / "catalog.py"
    )
    mod_name = "_alembic_prompt_catalog_seed"
    spec = importlib.util.spec_from_file_location(mod_name, catalog_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load prompt catalog from {catalog_path}")
    catalog_mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = catalog_mod
    spec.loader.exec_module(catalog_mod)
    PROMPT_CATALOG = catalog_mod.PROMPT_CATALOG

    versions = sa.table(
        "platform_prompt_versions",
        sa.column("id", sa.Integer),
        sa.column("prompt_key", sa.String),
        sa.column("version", sa.Integer),
        sa.column("body", sa.Text),
        sa.column("notes", sa.Text),
    )
    active = sa.table(
        "platform_prompt_active",
        sa.column("prompt_key", sa.String),
        sa.column("active_version_id", sa.Integer),
    )
    for defn in PROMPT_CATALOG:
        exists = conn.execute(
            sa.text(
                "SELECT 1 FROM platform_prompt_versions WHERE prompt_key = :k LIMIT 1"
            ),
            {"k": defn.key},
        ).first()
        if exists:
            continue
        conn.execute(
            versions.insert().values(
                prompt_key=defn.key,
                version=1,
                body=defn.default_body,
                notes="Seeded from code catalog",
            )
        )
        row_id = conn.execute(
            sa.text(
                "SELECT id FROM platform_prompt_versions "
                "WHERE prompt_key = :k AND version = 1"
            ),
            {"k": defn.key},
        ).scalar_one()
        conn.execute(
            active.insert().values(prompt_key=defn.key, active_version_id=row_id)
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _has_table(conn, "platform_prompt_active"):
        op.drop_table("platform_prompt_active")
    if _has_index(conn, "platform_prompt_versions", "ix_platform_prompt_versions_prompt_key"):
        op.drop_index(
            "ix_platform_prompt_versions_prompt_key",
            table_name="platform_prompt_versions",
        )
    if _has_table(conn, "platform_prompt_versions"):
        op.drop_table("platform_prompt_versions")
