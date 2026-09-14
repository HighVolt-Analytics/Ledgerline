"""Add document_type_adoption_lineage table.

Revision ID: 118
Revises: 117
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "118"
down_revision: Union[str, None] = "117"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_type_adoption_lineage",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("org_doc_type_code", sa.String(length=16), nullable=False),
        sa.Column("source_dictionary_code", sa.String(length=16), nullable=False),
        sa.Column("source_dictionary_version", sa.Integer(), nullable=False),
        sa.Column(
            "adopted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dt_adoption_lineage_tenant_org",
        "document_type_adoption_lineage",
        ["tenant_id", "org_doc_type_code"],
    )
    op.create_index(
        op.f("ix_document_type_adoption_lineage_tenant_id"),
        "document_type_adoption_lineage",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_document_type_adoption_lineage_tenant_id"),
        table_name="document_type_adoption_lineage",
    )
    op.drop_index("ix_dt_adoption_lineage_tenant_org", table_name="document_type_adoption_lineage")
    op.drop_table("document_type_adoption_lineage")
