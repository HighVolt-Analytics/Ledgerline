"""multi-tenant: organisations, users, mailboxes, org_id on invoices/vendors

Revision ID: 005
Revises: 004
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organisations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organisations_slug", "organisations", ["slug"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("admin", "member", name="user_role"),
            nullable=False,
            server_default="member",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "connected_mailboxes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "email", name="uq_mailbox_org_email"),
    )
    op.create_index("ix_connected_mailboxes_org_id", "connected_mailboxes", ["org_id"])
    op.create_index("ix_connected_mailboxes_email", "connected_mailboxes", ["email"])

    op.add_column("invoices", sa.Column("org_id", sa.Integer(), nullable=True))
    op.add_column(
        "invoices",
        sa.Column("connected_mailbox_id", sa.Integer(), nullable=True),
    )
    op.add_column("vendor_registry", sa.Column("org_id", sa.Integer(), nullable=True))

    op.execute(
        sa.text(
            "INSERT INTO organisations (name, slug) VALUES ('Default Organisation', 'default')"
        )
    )
    op.execute(sa.text("UPDATE invoices SET org_id = 1 WHERE org_id IS NULL"))
    op.execute(sa.text("UPDATE vendor_registry SET org_id = 1 WHERE org_id IS NULL"))

    op.alter_column("invoices", "org_id", nullable=False)
    op.alter_column("vendor_registry", "org_id", nullable=False)

    op.create_foreign_key(
        "fk_invoices_org_id", "invoices", "organisations", ["org_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_invoices_connected_mailbox_id",
        "invoices",
        "connected_mailboxes",
        ["connected_mailbox_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_vendor_registry_org_id",
        "vendor_registry",
        "organisations",
        ["org_id"],
        ["id"],
    )
    op.create_index("ix_invoices_org_id", "invoices", ["org_id"])

    op.drop_constraint("invoices_file_hash_key", "invoices", type_="unique")
    op.create_unique_constraint("uq_invoice_org_hash", "invoices", ["org_id", "file_hash"])

    op.drop_constraint("vendor_registry_vendor_slug_key", "vendor_registry", type_="unique")
    op.create_unique_constraint(
        "uq_vendor_org_slug", "vendor_registry", ["org_id", "vendor_slug"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_vendor_org_slug", "vendor_registry", type_="unique")
    op.create_unique_constraint(
        "vendor_registry_vendor_slug_key", "vendor_registry", ["vendor_slug"]
    )

    op.drop_constraint("uq_invoice_org_hash", "invoices", type_="unique")
    op.create_unique_constraint("invoices_file_hash_key", "invoices", ["file_hash"])

    op.drop_constraint("fk_vendor_registry_org_id", "vendor_registry", type_="foreignkey")
    op.drop_constraint("fk_invoices_connected_mailbox_id", "invoices", type_="foreignkey")
    op.drop_constraint("fk_invoices_org_id", "invoices", type_="foreignkey")
    op.drop_index("ix_invoices_org_id", table_name="invoices")
    op.drop_column("vendor_registry", "org_id")
    op.drop_column("invoices", "connected_mailbox_id")
    op.drop_column("invoices", "org_id")

    op.drop_table("connected_mailboxes")
    op.drop_table("users")
    op.drop_table("organisations")
    op.execute(sa.text("DROP TYPE IF EXISTS user_role"))
