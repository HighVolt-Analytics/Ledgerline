"""Slack workspace connections, webhook dedupe, and employee slack_user_id.

Revision ID: 108
Revises: 107
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "108"
down_revision: Union[str, None] = "107"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connected_slack_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("team_name", sa.String(length=256), nullable=True),
        sa.Column("bot_user_id", sa.String(length=64), nullable=True),
        sa.Column("app_id", sa.String(length=64), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["connected_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "team_id", name="uq_slack_tenant_team_id"),
    )
    op.create_index(
        "ix_connected_slack_accounts_tenant_id",
        "connected_slack_accounts",
        ["tenant_id"],
    )
    op.create_index(
        "ix_connected_slack_accounts_team_id",
        "connected_slack_accounts",
        ["team_id"],
    )

    op.create_table(
        "slack_webhook_dedupe",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "event_id", name="uq_slack_webhook_dedupe_tenant_event"
        ),
    )
    op.create_index(
        "ix_slack_webhook_dedupe_tenant_id",
        "slack_webhook_dedupe",
        ["tenant_id"],
    )
    op.create_index(
        "ix_slack_webhook_dedupe_event_id",
        "slack_webhook_dedupe",
        ["event_id"],
    )

    op.add_column(
        "invoices",
        sa.Column("slack_connection_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_invoices_slack_connection_id",
        "invoices",
        "connected_slack_accounts",
        ["slack_connection_id"],
        ["id"],
    )

    op.add_column(
        "employee_masters",
        sa.Column("slack_user_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_employee_masters_tenant_slack_user_id",
        "employee_masters",
        ["tenant_id", "slack_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_employee_masters_tenant_slack_user_id",
        table_name="employee_masters",
    )
    op.drop_column("employee_masters", "slack_user_id")

    op.drop_constraint("fk_invoices_slack_connection_id", "invoices", type_="foreignkey")
    op.drop_column("invoices", "slack_connection_id")

    op.drop_index("ix_slack_webhook_dedupe_event_id", table_name="slack_webhook_dedupe")
    op.drop_index("ix_slack_webhook_dedupe_tenant_id", table_name="slack_webhook_dedupe")
    op.drop_table("slack_webhook_dedupe")

    op.drop_index(
        "ix_connected_slack_accounts_team_id",
        table_name="connected_slack_accounts",
    )
    op.drop_index(
        "ix_connected_slack_accounts_tenant_id",
        table_name="connected_slack_accounts",
    )
    op.drop_table("connected_slack_accounts")
