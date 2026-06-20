"""Historical mailbox import jobs (date-range backfill).

Revision ID: 021
Revises: 020
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


def upgrade() -> None:
    op.create_table(
        "mailbox_sync_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("mailbox_id", sa.Integer(), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=False),
        sa.Column("mark_processed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=STATUS_QUEUED),
        sa.Column("messages_scanned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attachments_ingested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("messages_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invoices_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["mailbox_id"], ["connected_mailboxes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mailbox_sync_jobs_org_id", "mailbox_sync_jobs", ["org_id"])
    op.create_index("ix_mailbox_sync_jobs_mailbox_id", "mailbox_sync_jobs", ["mailbox_id"])
    op.create_index("ix_mailbox_sync_jobs_status", "mailbox_sync_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_mailbox_sync_jobs_status", table_name="mailbox_sync_jobs")
    op.drop_index("ix_mailbox_sync_jobs_mailbox_id", table_name="mailbox_sync_jobs")
    op.drop_index("ix_mailbox_sync_jobs_org_id", table_name="mailbox_sync_jobs")
    op.drop_table("mailbox_sync_jobs")
