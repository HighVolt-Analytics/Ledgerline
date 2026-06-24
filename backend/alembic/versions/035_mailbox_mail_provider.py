"""Add mail_provider to mailbox tables for Google vs Microsoft OAuth."""

from alembic import op
import sqlalchemy as sa

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "connected_mailboxes",
        sa.Column("mail_provider", sa.String(length=32), nullable=False, server_default="microsoft"),
    )
    op.add_column(
        "mailbox_connection_requests",
        sa.Column("mail_provider", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mailbox_connection_requests", "mail_provider")
    op.drop_column("connected_mailboxes", "mail_provider")
