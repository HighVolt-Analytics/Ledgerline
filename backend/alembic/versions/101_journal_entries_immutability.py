"""Make journal_entries append-only: block UPDATE and DELETE at the DB layer.

Corrections now go through journal_reversal_service.reverse_batch(), which
posts a new balanced batch with signs swapped rather than mutating history.
This migration makes that the *only* way to correct a posting, regardless
of which application code path runs — remap, invoice reset, and stranded-
journal cleanup are all updated in this same change to call reverse_batch()
instead of session.delete().

Revision ID: 101
Revises: 100
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "101"
down_revision: Union[str, None] = "100"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION block_journal_entry_mutation() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION
                    'journal_entries is append-only — reverse batch % instead of updating/deleting entry %',
                    COALESCE(OLD.batch_id, NEW.batch_id), OLD.id
                    USING ERRCODE = '23001';
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    conn.execute(
        sa.text(
            'DROP TRIGGER IF EXISTS trg_journal_entries_immutable ON "journal_entries"'
        )
    )
    conn.execute(
        sa.text(
            """
            CREATE TRIGGER trg_journal_entries_immutable
            BEFORE UPDATE OR DELETE ON journal_entries
            FOR EACH ROW
            EXECUTE FUNCTION block_journal_entry_mutation();
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            'DROP TRIGGER IF EXISTS trg_journal_entries_immutable ON "journal_entries"'
        )
    )
    conn.execute(sa.text("DROP FUNCTION IF EXISTS block_journal_entry_mutation()"))
