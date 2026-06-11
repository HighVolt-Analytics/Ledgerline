"""Invoice fields for vendor master detection signals."""

from alembic import op
import sqlalchemy as sa

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("billing_address", sa.Text(), nullable=True))
    op.add_column("invoices", sa.Column("bank_bsb", sa.String(16), nullable=True))
    op.add_column("invoices", sa.Column("bank_account", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("invoices", "bank_account")
    op.drop_column("invoices", "bank_bsb")
    op.drop_column("invoices", "billing_address")
