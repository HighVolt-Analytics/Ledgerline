"""Add settlement journal linkage and bank account rule-book defaults.

Revision ID: 064
Revises: 063
"""

from __future__ import annotations

import json
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "064"
down_revision: Union[str, None] = "063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BANK_ACCOUNT_NAME = "Bank Account"
_BANK_COA_CODE = "1000"


def _merge_bank_into_config(raw: Any) -> dict[str, Any]:
    config = dict(raw) if isinstance(raw, dict) else {}
    posting = dict(config.get("posting_defaults") or {})
    if not posting.get("bank_account"):
        posting["bank_account"] = _BANK_ACCOUNT_NAME
    config["posting_defaults"] = posting

    chart = list(config.get("chart_of_accounts") or [])
    bank_name = str(posting.get("bank_account") or _BANK_ACCOUNT_NAME).strip()
    has_bank = any(
        isinstance(row, dict)
        and str(row.get("name") or "").strip().lower() == bank_name.lower()
        for row in chart
    )
    if not has_bank:
        chart.insert(
            0,
            {"code": _BANK_COA_CODE, "name": bank_name, "type": "Asset", "sub_ledgers": []},
        )
    config["chart_of_accounts"] = chart
    return config


def upgrade() -> None:
    journal_entry_kind = sa.Enum(
        "invoice_accrual",
        "payment_settlement",
        "collection_settlement",
        name="journal_entry_kind",
    )
    journal_entry_kind.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "journal_entries",
        sa.Column(
            "entry_kind",
            journal_entry_kind,
            nullable=False,
            server_default="invoice_accrual",
        ),
    )
    op.add_column(
        "journal_entries",
        sa.Column("payment_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "journal_entries",
        sa.Column("collection_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_journal_entries_payment_id",
        "journal_entries",
        "payments",
        ["payment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_journal_entries_collection_id",
        "journal_entries",
        "collections",
        ["collection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_journal_entries_entry_kind", "journal_entries", ["entry_kind"])
    op.create_index("ix_journal_entries_payment_id", "journal_entries", ["payment_id"])
    op.create_index(
        "ix_journal_entries_collection_id",
        "journal_entries",
        ["collection_id"],
    )

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT tenant_id, config FROM tenant_rule_book_configs")
    ).fetchall()
    for tenant_id, config_raw in rows:
        if isinstance(config_raw, str):
            config_raw = json.loads(config_raw)
        merged = _merge_bank_into_config(config_raw)
        conn.execute(
            sa.text(
                "UPDATE tenant_rule_book_configs SET config = :config WHERE tenant_id = :tenant_id"
            ),
            {"config": json.dumps(merged), "tenant_id": tenant_id},
        )


def downgrade() -> None:
    op.drop_index("ix_journal_entries_collection_id", table_name="journal_entries")
    op.drop_index("ix_journal_entries_payment_id", table_name="journal_entries")
    op.drop_index("ix_journal_entries_entry_kind", table_name="journal_entries")
    op.drop_constraint("fk_journal_entries_collection_id", "journal_entries", type_="foreignkey")
    op.drop_constraint("fk_journal_entries_payment_id", "journal_entries", type_="foreignkey")
    op.drop_column("journal_entries", "collection_id")
    op.drop_column("journal_entries", "payment_id")
    op.drop_column("journal_entries", "entry_kind")
    sa.Enum(name="journal_entry_kind").drop(op.get_bind(), checkfirst=True)
