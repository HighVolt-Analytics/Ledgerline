"""Add org_id to audit_logs for org-scoped governance events.

Revision ID: 011
Revises: 010
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("org_id", sa.Integer(), nullable=True))
    op.create_index("ix_audit_logs_org_id", "audit_logs", ["org_id"])
    op.create_foreign_key(
        "fk_audit_logs_org_id",
        "audit_logs",
        "organisations",
        ["org_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        """
        UPDATE audit_logs
        SET org_id = invoices.org_id
        FROM invoices
        WHERE audit_logs.invoice_id = invoices.id
          AND audit_logs.org_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_audit_logs_org_id", "audit_logs", type_="foreignkey")
    op.drop_index("ix_audit_logs_org_id", table_name="audit_logs")
    op.drop_column("audit_logs", "org_id")
