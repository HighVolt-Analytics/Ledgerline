"""Link payments to vendor_registry for deterministic payout lookup.

Revision ID: 040
Revises: 039
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "040"
down_revision: Union[str, None] = "039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("vendor_registry_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_payments_vendor_registry_id",
        "payments",
        "vendor_registry",
        ["vendor_registry_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_payments_vendor_registry_id",
        "payments",
        ["vendor_registry_id"],
    )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            WITH matched AS (
                SELECT
                    p.id AS payment_id,
                    vr.id AS vendor_registry_id
                FROM payments p
                JOIN invoices i ON i.id = p.invoice_id
                JOIN vendor_registry vr
                  ON vr.tenant_id = p.tenant_id
                 AND vr.vendor_slug = i.storage_vendor_slug
                WHERE p.vendor_registry_id IS NULL
                  AND i.storage_vendor_slug IS NOT NULL
                  AND i.storage_vendor_slug <> 'unknown'
            )
            UPDATE payments p
            SET vendor_registry_id = matched.vendor_registry_id
            FROM matched
            WHERE p.id = matched.payment_id
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE payments AS p
            SET vendor_registry_id = vr.id
            FROM vendor_registry AS vr
            WHERE p.vendor_registry_id IS NULL
              AND p.vendor IS NOT NULL
              AND trim(p.vendor) <> ''
              AND vr.tenant_id = p.tenant_id
              AND lower(trim(vr.vendor_name)) = lower(trim(p.vendor))
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_payments_vendor_registry_id", table_name="payments")
    op.drop_constraint("fk_payments_vendor_registry_id", "payments", type_="foreignkey")
    op.drop_column("payments", "vendor_registry_id")
