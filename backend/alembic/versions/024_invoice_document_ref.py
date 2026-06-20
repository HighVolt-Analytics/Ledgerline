"""Add stable org-scoped document_ref to invoices.

Revision ID: 024
Revises: 023
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "024"
down_revision: Union[str, None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("document_ref", sa.String(length=32), nullable=True))
    op.create_index("ix_invoices_document_ref", "invoices", ["document_ref"], unique=False)

    connection = op.get_bind()
    org_rows = connection.execute(sa.text("SELECT DISTINCT org_id FROM invoices ORDER BY org_id"))
    for (org_id,) in org_rows:
        invoice_rows = connection.execute(
            sa.text(
                """
                SELECT id
                FROM invoices
                WHERE org_id = :org_id
                ORDER BY created_at ASC, id ASC
                """
            ),
            {"org_id": org_id},
        )
        for seq, (invoice_id,) in enumerate(invoice_rows, start=1):
            connection.execute(
                sa.text(
                    """
                    UPDATE invoices
                    SET document_ref = :document_ref
                    WHERE id = :invoice_id
                    """
                ),
                {
                    "invoice_id": invoice_id,
                    "document_ref": f"DOC-{seq:04d}",
                },
            )

    op.create_index(
        "uq_invoice_org_document_ref",
        "invoices",
        ["org_id", "document_ref"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_invoice_org_document_ref", table_name="invoices")
    op.drop_index("ix_invoices_document_ref", table_name="invoices")
    op.drop_column("invoices", "document_ref")
