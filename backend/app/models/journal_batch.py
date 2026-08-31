"""Journal batch — the append-only posting unit for journal entries.

Every call to persist_journal_lines() creates exactly one JournalBatch and
attaches every JournalEntry it inserts to that batch. A DB-level deferred
constraint trigger (see migration 099) sums debit/credit per batch_id at
commit and rejects the transaction if a batch does not balance — this closes
the gap where journal_generator.is_balanced() was only checked by callers,
never enforced by the database itself.

Phase 2 (migration 100) adds `reversed_by_batch_id` so corrections can be
posted as a reversing batch instead of deleting/rewriting history.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.journal import JournalEntryKind

if TYPE_CHECKING:
    from app.models.journal import JournalEntry


class JournalBatchStatus(str, enum.Enum):
    POSTED = "posted"
    REVERSED = "reversed"


class JournalBatch(Base):
    __tablename__ = "journal_batches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    # Nullable: settlement batches aren't tied to a single invoice the way
    # accrual batches are, but we keep the FK for audit/query convenience
    # whenever there is one natural invoice to point at.
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    entry_kind: Mapped[JournalEntryKind] = mapped_column(
        # Reuses the existing "journal_entry_kind" Postgres enum type created
        # by migration 064 for JournalEntry.entry_kind — the migration must
        # NOT try to re-create this type (create_type=False on that column).
        Enum(
            JournalEntryKind,
            name="journal_entry_kind",
            values_callable=lambda kinds: [k.value for k in kinds],
        ),
        default=JournalEntryKind.INVOICE_ACCRUAL,
        index=True,
    )
    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    collection_id: Mapped[int | None] = mapped_column(
        ForeignKey("collections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        default=JournalBatchStatus.POSTED.value,
        server_default=JournalBatchStatus.POSTED.value,
        index=True,
    )
    # Set on the ORIGINAL batch once it has been reversed (Phase 2). The
    # reversing batch itself is a normal POSTED batch and does not point
    # back — walk reversed_by_batch_id forward from the original instead.
    reversed_by_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("journal_batches.id", ondelete="SET NULL"),
        nullable=True,
    )
    reversal_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)

    entries: Mapped[list["JournalEntry"]] = relationship(
        back_populates="batch",
        foreign_keys="JournalEntry.batch_id",
    )
