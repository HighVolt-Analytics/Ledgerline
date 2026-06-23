"""Migrate tenants.id and all tenant_id FKs from integer to UUID.

Revision ID: 029
Revises: 028

Testing tenant  -> 550e8400-e29b-41d4-a716-446655440001
Platform tenant -> 550e8400-e29b-41d4-a716-446655440002
"""

from typing import Sequence, Union
import uuid as uuid_lib

import sqlalchemy as sa
from alembic import op

revision: str = "029"
down_revision: Union[str, None] = "028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TESTING_UUID = "550e8400-e29b-41d4-a716-446655440001"
PLATFORM_UUID = "550e8400-e29b-41d4-a716-446655440002"

_TENANT_FK_TABLES = (
    "users",
    "invoices",
    "vendor_registry",
    "vendor_masters",
    "employee_masters",
    "pending_vendors",
    "purchase_orders",
    "payments",
    "connected_mailboxes",
    "connected_whatsapp_accounts",
    "mailbox_connection_requests",
    "mailbox_sync_jobs",
    "audit_logs",
    "daily_reconciliations",
    "user_tenant_mappings",
    "tenant_modules",
    "email_verification_otp",
)

_CASCADE_FK_TABLES = tuple(
    t for t in _TENANT_FK_TABLES if t not in ("audit_logs", "email_verification_otp")
)


def _drop_tenant_fks(conn, table: str) -> None:
    rows = conn.execute(
        sa.text(
            """
            SELECT tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.table_schema = 'public'
              AND tc.table_name = :table
              AND tc.constraint_type = 'FOREIGN KEY'
              AND kcu.column_name = 'tenant_id'
            """
        ),
        {"table": table},
    ).fetchall()
    for (name,) in rows:
        conn.execute(sa.text(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{name}"'))


def upgrade() -> None:
    conn = op.get_bind()
    # Azure Postgres blocks CREATE EXTENSION pgcrypto; assign UUIDs in Python instead.
    # Drop other DB sessions so DDL does not deadlock with app workers.
    conn.execute(
        sa.text(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid <> pg_backend_pid()
            """
        )
    )
    # Grab exclusive locks up front so app workers cannot interleave reads and deadlock DDL.
    lock_tables = ["tenants", *_TENANT_FK_TABLES]
    conn.execute(
        sa.text(
            "LOCK TABLE "
            + ", ".join(f'"{t}"' for t in lock_tables)
            + " IN ACCESS EXCLUSIVE MODE"
        )
    )

    op.add_column("tenants", sa.Column("id_uuid", sa.UUID(), nullable=True))
    conn.execute(
        sa.text("UPDATE tenants SET id_uuid = CAST(:uuid AS uuid) WHERE slug = 'testing'"),
        {"uuid": TESTING_UUID},
    )
    conn.execute(
        sa.text("UPDATE tenants SET id_uuid = CAST(:uuid AS uuid) WHERE slug = 'platform'"),
        {"uuid": PLATFORM_UUID},
    )
    remaining = conn.execute(
        sa.text("SELECT id FROM tenants WHERE id_uuid IS NULL")
    ).fetchall()
    for (old_id,) in remaining:
        conn.execute(
            sa.text("UPDATE tenants SET id_uuid = CAST(:uuid AS uuid) WHERE id = :old_id"),
            {"uuid": str(uuid_lib.uuid4()), "old_id": old_id},
        )
    op.alter_column("tenants", "id_uuid", nullable=False)

    for table in _TENANT_FK_TABLES:
        conn.execute(
            sa.text(
                f"""
                DO $$
                BEGIN
                  IF EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = '{table}'
                  ) THEN
                    ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id_uuid UUID;
                  END IF;
                END $$;
                """
            )
        )
        conn.execute(
            sa.text(
                f"""
                UPDATE {table} child
                SET tenant_id_uuid = t.id_uuid
                FROM tenants t
                WHERE child.tenant_id = t.id
                  AND child.tenant_id IS NOT NULL
                """
            )
        )

    for table in _TENANT_FK_TABLES:
        _drop_tenant_fks(conn, table)

    # Drop RLS policies before renaming/dropping tenant_id (policies reference the old column).
    for table in _TENANT_FK_TABLES:
        conn.execute(
            sa.text(
                f"""
                DO $$
                BEGIN
                  IF EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE schemaname = 'public'
                      AND tablename = '{table}'
                      AND policyname = 'tenant_isolation'
                  ) THEN
                    DROP POLICY tenant_isolation ON {table};
                  END IF;
                END $$;
                """
            )
        )

    conn.execute(sa.text("ALTER TABLE tenants DROP CONSTRAINT IF EXISTS tenants_pkey"))
    op.drop_column("tenants", "id")
    op.alter_column("tenants", "id_uuid", new_column_name="id")
    conn.execute(sa.text("ALTER TABLE tenants ADD PRIMARY KEY (id)"))

    for table in _TENANT_FK_TABLES:
        conn.execute(
            sa.text(
                f"""
                DO $$
                BEGIN
                  IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = '{table}'
                      AND column_name = 'tenant_id'
                  ) THEN
                    ALTER TABLE {table} DROP COLUMN tenant_id;
                  END IF;
                  IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = '{table}'
                      AND column_name = 'tenant_id_uuid'
                  ) THEN
                    ALTER TABLE {table} RENAME COLUMN tenant_id_uuid TO tenant_id;
                  END IF;
                END $$;
                """
            )
        )

    for table in _CASCADE_FK_TABLES:
        conn.execute(
            sa.text(
                f"""
                DO $$
                BEGIN
                  IF EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = '{table}'
                  ) THEN
                    ALTER TABLE {table}
                      ADD CONSTRAINT fk_{table}_tenant_id
                      FOREIGN KEY (tenant_id) REFERENCES tenants(id)
                      ON DELETE CASCADE;
                  END IF;
                END $$;
                """
            )
        )

    for table in ("audit_logs", "email_verification_otp"):
        conn.execute(
            sa.text(
                f"""
                DO $$
                BEGIN
                  IF EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'fk_{table}_tenant_id'
                  ) THEN
                    ALTER TABLE {table} DROP CONSTRAINT fk_{table}_tenant_id;
                  END IF;
                  IF EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = '{table}'
                  ) THEN
                    ALTER TABLE {table}
                      ADD CONSTRAINT fk_{table}_tenant_id
                      FOREIGN KEY (tenant_id) REFERENCES tenants(id)
                      ON DELETE SET NULL;
                  END IF;
                END $$;
                """
            )
        )

    # RLS policies: integer cast -> uuid cast
    for table in _TENANT_FK_TABLES:
        conn.execute(
            sa.text(
                f"""
                DO $$
                BEGIN
                  IF EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE schemaname = 'public'
                      AND tablename = '{table}'
                      AND policyname = 'tenant_isolation'
                  ) THEN
                    DROP POLICY tenant_isolation ON {table};
                    CREATE POLICY tenant_isolation ON {table}
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


def downgrade() -> None:
    raise NotImplementedError("029 downgrade not supported")
