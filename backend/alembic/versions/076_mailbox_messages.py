"""Mailbox message lifecycle table (DB-first outcomes).

Revision ID: 076
Revises: 075
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "076"
down_revision: Union[str, None] = "075"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(conn, table: str) -> bool:
    return inspect(conn).has_table(table)


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

    if not _has_table(conn, "mailbox_messages"):
        op.create_table(
            "mailbox_messages",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("connected_mailbox_id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("stable_message_id", sa.String(length=512), nullable=False),
            sa.Column("provider_message_id", sa.String(length=512), nullable=True),
            sa.Column("outcome", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("skip_reason", sa.String(length=64), nullable=True),
            sa.Column("folder_synced_at", sa.DateTime(timezone=True), nullable=True),
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
                ["connected_mailbox_id"],
                ["connected_mailboxes.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "connected_mailbox_id",
                "stable_message_id",
                name="uq_mailbox_messages_mailbox_stable_id",
            ),
        )
    if not _has_index(conn, "mailbox_messages", "ix_mailbox_messages_tenant_id"):
        op.create_index("ix_mailbox_messages_tenant_id", "mailbox_messages", ["tenant_id"])
    if not _has_index(conn, "mailbox_messages", "ix_mailbox_messages_connected_mailbox_id"):
        op.create_index(
            "ix_mailbox_messages_connected_mailbox_id",
            "mailbox_messages",
            ["connected_mailbox_id"],
        )
    if not _has_index(conn, "mailbox_messages", "ix_mailbox_messages_stable_message_id"):
        op.create_index(
            "ix_mailbox_messages_stable_message_id",
            "mailbox_messages",
            ["stable_message_id"],
        )
    if not _has_index(conn, "mailbox_messages", "ix_mailbox_messages_outcome"):
        op.create_index("ix_mailbox_messages_outcome", "mailbox_messages", ["outcome"])

    _enable_rls(conn, "mailbox_messages")
    # Drop server default after create so app owns defaults going forward.
    op.alter_column("mailbox_messages", "outcome", server_default=None)


def downgrade() -> None:
    conn = op.get_bind()
    _disable_rls(conn, "mailbox_messages")
    if _has_index(conn, "mailbox_messages", "ix_mailbox_messages_outcome"):
        op.drop_index("ix_mailbox_messages_outcome", table_name="mailbox_messages")
    if _has_index(conn, "mailbox_messages", "ix_mailbox_messages_stable_message_id"):
        op.drop_index("ix_mailbox_messages_stable_message_id", table_name="mailbox_messages")
    if _has_index(conn, "mailbox_messages", "ix_mailbox_messages_connected_mailbox_id"):
        op.drop_index(
            "ix_mailbox_messages_connected_mailbox_id",
            table_name="mailbox_messages",
        )
    if _has_index(conn, "mailbox_messages", "ix_mailbox_messages_tenant_id"):
        op.drop_index("ix_mailbox_messages_tenant_id", table_name="mailbox_messages")
    if _has_table(conn, "mailbox_messages"):
        op.drop_table("mailbox_messages")
