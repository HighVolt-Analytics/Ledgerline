"""Normalize invoice document_ref format to DT-{n}.

Revision ID: 025
Revises: 024
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "025"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, org_id, document_ref FROM invoices ORDER BY org_id, id")
    )
    for invoice_id, org_id, raw_ref in rows:
        value = (raw_ref or "").strip().upper()
        seq = None
        if value.startswith("DOC-") or value.startswith("DT-"):
            token = value.split("-", 1)[1].strip()
            if token.isdigit():
                seq = int(token)
        if seq is None:
            seq_rows = connection.execute(
                sa.text(
                    """
                    SELECT COALESCE(MAX(CAST(SUBSTRING(document_ref FROM '[0-9]+$') AS INTEGER)), 0)
                    FROM invoices
                    WHERE org_id = :org_id
                    """
                ),
                {"org_id": org_id},
            )
            seq = int(seq_rows.scalar() or 0) + 1
        connection.execute(
            sa.text("UPDATE invoices SET document_ref = :ref WHERE id = :id"),
            {"id": invoice_id, "ref": f"DT-{seq}"},
        )


def downgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, document_ref FROM invoices"))
    for invoice_id, raw_ref in rows:
        value = (raw_ref or "").strip().upper()
        seq = value.split("-", 1)[1] if value.startswith("DT-") else "0"
        if not str(seq).isdigit():
            seq = "0"
        connection.execute(
            sa.text("UPDATE invoices SET document_ref = :ref WHERE id = :id"),
            {"id": invoice_id, "ref": f"DOC-{int(seq):04d}"},
        )
