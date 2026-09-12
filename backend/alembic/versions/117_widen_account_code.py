"""Widen account_code columns for parent-sub COA composites.

Revision ID: 117
Revises: 116

Rule book allows codes up to 32 chars; nested TE mapping stores
``{parent}-{sub}`` which exceeds the legacy invoices/journal varchar(20).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "117"
down_revision: Union[str, None] = "116"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACCOUNT_CODE_LEN = 64


def upgrade() -> None:
    op.alter_column(
        "invoices",
        "account_code",
        existing_type=sa.String(length=20),
        type_=sa.String(length=_ACCOUNT_CODE_LEN),
        existing_nullable=True,
    )
    op.alter_column(
        "journal_entries",
        "account_code",
        existing_type=sa.String(length=20),
        type_=sa.String(length=_ACCOUNT_CODE_LEN),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "journal_entries",
        "account_code",
        existing_type=sa.String(length=_ACCOUNT_CODE_LEN),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
    op.alter_column(
        "invoices",
        "account_code",
        existing_type=sa.String(length=_ACCOUNT_CODE_LEN),
        type_=sa.String(length=20),
        existing_nullable=True,
    )
