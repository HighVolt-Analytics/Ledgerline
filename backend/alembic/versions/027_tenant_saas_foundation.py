"""SaaS tenant foundation: rename org→tenant, auth_accounts, RLS prep, data consolidation.

Revision ID: 027
Revises: 026
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "027"
down_revision: Union[str, None] = "026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TENANT_SCOPED_TABLES = (
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
)


def _rename_org_id_to_tenant_id(table: str) -> None:
    op.alter_column(table, "org_id", new_column_name="tenant_id")
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE indexname = 'ix_{table}_org_id'
              ) THEN
                ALTER INDEX ix_{table}_org_id RENAME TO ix_{table}_tenant_id;
              END IF;
            END $$;
            """
        )
    )


def upgrade() -> None:
    conn = op.get_bind()

    # --- Rename organisations → tenants ---
    op.rename_table("organisations", "tenants")
    op.execute("ALTER INDEX IF EXISTS ix_organisations_slug RENAME TO ix_tenants_slug")

    op.add_column(
        "tenants",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "tenants",
        sa.Column("is_platform", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "lifecycle_status",
            sa.String(20),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column("tenants", sa.Column("settings_json", sa.JSON(), nullable=True))

    # --- Rename org_id → tenant_id on scoped tables ---
    for table in _TENANT_SCOPED_TABLES:
        _rename_org_id_to_tenant_id(table)

    # --- user_org_memberships → user_tenant_mappings ---
    op.rename_table("user_org_memberships", "user_tenant_mappings")
    op.alter_column("user_tenant_mappings", "org_id", new_column_name="tenant_id")
    op.execute(
        "ALTER INDEX IF EXISTS ix_user_org_memberships_org_id "
        "RENAME TO ix_user_tenant_mappings_tenant_id"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_user_org_memberships_user_id "
        "RENAME TO ix_user_tenant_mappings_user_id"
    )
    op.execute(
        "ALTER TABLE user_tenant_mappings "
        "RENAME CONSTRAINT uq_user_org TO uq_user_tenant"
    )

    op.add_column(
        "user_tenant_mappings",
        sa.Column("role", sa.String(32), nullable=False, server_default="member"),
    )
    op.add_column(
        "user_tenant_mappings",
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
    )
    op.add_column(
        "user_tenant_mappings",
        sa.Column("default_tenant", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "user_tenant_mappings",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    # --- auth_accounts ---
    op.create_table(
        "auth_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_auth_accounts_email"),
    )
    op.create_index("ix_auth_accounts_email", "auth_accounts", ["email"], unique=True)

    op.add_column("users", sa.Column("auth_account_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_users_auth_account_id",
        "users",
        "auth_accounts",
        ["auth_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_users_auth_account_id", "users", ["auth_account_id"])

    # Populate auth_accounts from existing users
    conn.execute(
        sa.text(
            """
            INSERT INTO auth_accounts (email, password_hash, is_blocked, created_at)
            SELECT DISTINCT ON (lower(email))
                   lower(email),
                   password_hash,
                   NOT is_active,
                   COALESCE(created_at, now())
            FROM users
            ORDER BY lower(email), id
            ON CONFLICT (email) DO NOTHING
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE users u
            SET auth_account_id = a.id
            FROM auth_accounts a
            WHERE lower(u.email) = a.email
            """
        )
    )

    # Drop global unique on users.email; add per-tenant unique
    op.drop_index("ix_users_email", table_name="users")
    op.create_index("ix_users_email", "users", ["email"], unique=False)
    op.create_unique_constraint("uq_users_tenant_email", "users", ["tenant_id", "email"])

    # Sync membership roles from users
    conn.execute(
        sa.text(
            """
            UPDATE user_tenant_mappings m
            SET role = u.role::text,
                status = 'active',
                is_active = true
            FROM users u
            WHERE m.user_id = u.id
            """
        )
    )

    # --- daily_reconciliations tenant scope ---
    op.add_column(
        "daily_reconciliations",
        sa.Column("tenant_id", sa.Integer(), nullable=True),
    )
    # Assign to first tenant before NOT NULL
    conn.execute(
        sa.text(
            """
            UPDATE daily_reconciliations
            SET tenant_id = (SELECT id FROM tenants ORDER BY id LIMIT 1)
            WHERE tenant_id IS NULL
            """
        )
    )
    op.alter_column("daily_reconciliations", "tenant_id", nullable=False)
    op.drop_constraint("daily_reconciliations_date_key", "daily_reconciliations", type_="unique")
    op.create_foreign_key(
        "fk_daily_reconciliations_tenant_id",
        "daily_reconciliations",
        "tenants",
        ["tenant_id"],
        ["id"],
    )
    op.create_index("ix_daily_reconciliations_tenant_id", "daily_reconciliations", ["tenant_id"])
    op.create_unique_constraint(
        "uq_daily_reconciliations_tenant_date",
        "daily_reconciliations",
        ["tenant_id", "date"],
    )

    # --- tenant_modules ---
    op.create_table(
        "tenant_modules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("module_key", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "module_key", name="uq_tenant_modules_tenant_key"),
    )
    op.create_index("ix_tenant_modules_tenant_id", "tenant_modules", ["tenant_id"])

    # --- email_verification_otp (audit) ---
    op.create_table(
        "email_verification_otp",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("auth_account_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("otp_hash", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["auth_account_id"], ["auth_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- Data consolidation: single Testing tenant ---
    row = conn.execute(
        sa.text("SELECT id FROM tenants WHERE slug = 'testing' LIMIT 1")
    ).fetchone()
    if row:
        testing_id = row[0]
        conn.execute(
            sa.text("UPDATE tenants SET name = 'Testing', slug = 'testing' WHERE id = :id"),
            {"id": testing_id},
        )
    else:
        existing = conn.execute(sa.text("SELECT id FROM tenants ORDER BY id LIMIT 1")).fetchone()
        if existing:
            testing_id = existing[0]
            conn.execute(
                sa.text(
                    "UPDATE tenants SET name = 'Testing', slug = 'testing' WHERE id = :id"
                ),
                {"id": testing_id},
            )
        else:
            result = conn.execute(
                sa.text(
                    """
                    INSERT INTO tenants (name, slug, is_active, is_platform, lifecycle_status)
                    VALUES ('Testing', 'testing', true, false, 'active')
                    RETURNING id
                    """
                )
            )
            testing_id = result.fetchone()[0]

    # Merge all tenants into testing tenant
    other_ids = conn.execute(
        sa.text("SELECT id FROM tenants WHERE id != :tid"),
        {"tid": testing_id},
    ).fetchall()
    for (oid,) in other_ids:
        for table in _TENANT_SCOPED_TABLES:
            conn.execute(
                sa.text(f"UPDATE {table} SET tenant_id = :tid WHERE tenant_id = :oid"),
                {"tid": testing_id, "oid": oid},
            )
        conn.execute(
            sa.text(
                "UPDATE user_tenant_mappings SET tenant_id = :tid WHERE tenant_id = :oid"
            ),
            {"tid": testing_id, "oid": oid},
        )
        conn.execute(
            sa.text("UPDATE daily_reconciliations SET tenant_id = :tid WHERE tenant_id = :oid"),
            {"tid": testing_id, "oid": oid},
        )
        conn.execute(sa.text("DELETE FROM tenants WHERE id = :oid"), {"oid": oid})

    # vishnu@highvolt.tech as admin
    conn.execute(
        sa.text(
            """
            UPDATE users SET role = 'admin'
            WHERE lower(email) = 'vishnu@highvolt.tech'
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE user_tenant_mappings m
            SET role = 'admin', default_tenant = true, status = 'active', is_active = true
            FROM users u
            WHERE m.user_id = u.id AND lower(u.email) = 'vishnu@highvolt.tech'
            """
        )
    )

    # Seed tenant modules
    for mod in ("purchase", "expenses", "team_expenses", "vault", "rule_book"):
        conn.execute(
            sa.text(
                """
                INSERT INTO tenant_modules (tenant_id, module_key, is_active)
                VALUES (:tid, :key, true)
                ON CONFLICT (tenant_id, module_key) DO NOTHING
                """
            ),
            {"tid": testing_id, "key": mod},
        )

    # Backfill audit_logs null tenant_id
    conn.execute(
        sa.text(
            """
            UPDATE audit_logs a
            SET tenant_id = i.tenant_id
            FROM invoices i
            WHERE a.invoice_id = i.id AND a.tenant_id IS NULL
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE audit_logs SET tenant_id = :tid WHERE tenant_id IS NULL
            """
        ),
        {"tid": testing_id},
    )


def downgrade() -> None:
    raise NotImplementedError("027 downgrade not supported")
