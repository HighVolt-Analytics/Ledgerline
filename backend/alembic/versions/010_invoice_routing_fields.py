"""Phase 5 — invoice routing and evaluation fields.

Revision ID: 010
Revises: 009
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("route_target", sa.String(100)))
    op.add_column("invoices", sa.Column("matched_rule_ids", sa.Text()))
    op.add_column("invoices", sa.Column("vendor_confidence", sa.Float()))
    op.add_column("invoices", sa.Column("evaluation_status", sa.String(32)))
    op.create_index("ix_invoices_route_target", "invoices", ["route_target"])
    op.create_index("ix_invoices_evaluation_status", "invoices", ["evaluation_status"])


def downgrade() -> None:
    op.drop_index("ix_invoices_evaluation_status", table_name="invoices")
    op.drop_index("ix_invoices_route_target", table_name="invoices")
    op.drop_column("invoices", "evaluation_status")
    op.drop_column("invoices", "vendor_confidence")
    op.drop_column("invoices", "matched_rule_ids")
    op.drop_column("invoices", "route_target")
