"""Purchase order GL coding fields for inheritance."""

from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_orders", sa.Column("ledger", sa.String(255), nullable=True))
    op.add_column("purchase_orders", sa.Column("sub_ledger", sa.String(255), nullable=True))
    op.add_column("purchase_orders", sa.Column("tax_account", sa.String(100), nullable=True))
    op.add_column("purchase_orders", sa.Column("payable_account", sa.String(100), nullable=True))
    op.add_column("purchase_orders", sa.Column("purchase_rule_id", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("purchase_orders", "purchase_rule_id")
    op.drop_column("purchase_orders", "payable_account")
    op.drop_column("purchase_orders", "tax_account")
    op.drop_column("purchase_orders", "sub_ledger")
    op.drop_column("purchase_orders", "ledger")
