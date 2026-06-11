"""Invoice email subject and attachment name for live eval replay."""

from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("email_subject", sa.String(500), nullable=True))
    op.add_column("invoices", sa.Column("email_attachment_name", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("invoices", "email_attachment_name")
    op.drop_column("invoices", "email_subject")
