"""WhatsApp Cloud API connections and webhook dedupe.

Revision ID: 020
Revises: 019
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connected_whatsapp_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("phone_number_id", sa.String(length=64), nullable=False),
        sa.Column("phone_number", sa.String(length=32), nullable=True),
        sa.Column("display_name", sa.String(length=256), nullable=True),
        sa.Column("whatsapp_business_account_id", sa.String(length=64), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "connection_status",
            sa.String(length=32),
            nullable=False,
            server_default="connected",
        ),
        sa.Column(
            "integration_health",
            sa.String(length=32),
            nullable=False,
            server_default="connected",
        ),
        sa.Column("connected_by_user_id", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["connected_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "phone_number_id", name="uq_whatsapp_org_phone_id"),
    )
    op.create_index(
        "ix_connected_whatsapp_accounts_org_id",
        "connected_whatsapp_accounts",
        ["org_id"],
    )
    op.create_index(
        "ix_connected_whatsapp_accounts_phone_number_id",
        "connected_whatsapp_accounts",
        ["phone_number_id"],
    )
    op.create_index(
        "ix_connected_whatsapp_accounts_waba_id",
        "connected_whatsapp_accounts",
        ["whatsapp_business_account_id"],
    )

    op.create_table(
        "meta_webhook_dedupe",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("message_mid", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_mid"),
    )
    op.create_index(
        "ix_meta_webhook_dedupe_message_mid",
        "meta_webhook_dedupe",
        ["message_mid"],
    )

    op.add_column(
        "invoices",
        sa.Column("whatsapp_connection_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_invoices_whatsapp_connection_id",
        "invoices",
        "connected_whatsapp_accounts",
        ["whatsapp_connection_id"],
        ["id"],
    )
    op.add_column(
        "invoices",
        sa.Column("capture_source", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invoices", "capture_source")
    op.drop_constraint("fk_invoices_whatsapp_connection_id", "invoices", type_="foreignkey")
    op.drop_column("invoices", "whatsapp_connection_id")
    op.drop_index("ix_meta_webhook_dedupe_message_mid", "meta_webhook_dedupe")
    op.drop_table("meta_webhook_dedupe")
    op.drop_index("ix_connected_whatsapp_accounts_waba_id", "connected_whatsapp_accounts")
    op.drop_index(
        "ix_connected_whatsapp_accounts_phone_number_id",
        "connected_whatsapp_accounts",
    )
    op.drop_index("ix_connected_whatsapp_accounts_org_id", "connected_whatsapp_accounts")
    op.drop_table("connected_whatsapp_accounts")
