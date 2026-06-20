"""Normalize document_ref prefix from DT- to DOC-.

Revision ID: 026
Revises: 025
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "026"
down_revision: Union[str, None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, document_ref FROM invoices"))
    for invoice_id, raw_ref in rows:
        value = (raw_ref or "").strip()
        if not value:
            continue
        upper = value.upper()
        if upper.startswith("DT-"):
            seq = upper.split("-", 1)[1]
            if seq.isdigit():
                connection.execute(
                    sa.text("UPDATE invoices SET document_ref = :ref WHERE id = :id"),
                    {"id": invoice_id, "ref": f"DOC-{seq}"},
                )


def downgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, document_ref FROM invoices"))
    for invoice_id, raw_ref in rows:
        value = (raw_ref or "").strip().upper()
        if value.startswith("DOC-"):
            seq = value.split("-", 1)[1]
            if seq.isdigit():
                connection.execute(
                    sa.text("UPDATE invoices SET document_ref = :ref WHERE id = :id"),
                    {"id": invoice_id, "ref": f"DT-{int(seq)}"},
                )
