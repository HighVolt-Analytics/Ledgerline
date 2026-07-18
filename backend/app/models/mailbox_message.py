"""DB-first mailbox message lifecycle (poll/ingest/finalize)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

OUTCOME_PENDING = "pending"
OUTCOME_PROCESSED = "processed"
OUTCOME_EXCEPTION = "exception"
OUTCOME_SKIPPED = "skipped"

TERMINAL_OUTCOMES = frozenset(
    {OUTCOME_PROCESSED, OUTCOME_EXCEPTION, OUTCOME_SKIPPED}
)


class MailboxMessage(Base):
    __tablename__ = "mailbox_messages"
    __table_args__ = (
        UniqueConstraint(
            "connected_mailbox_id",
            "stable_message_id",
            name="uq_mailbox_messages_mailbox_stable_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id"),
        index=True,
    )
    connected_mailbox_id: Mapped[int] = mapped_column(
        ForeignKey("connected_mailboxes.id", ondelete="CASCADE"),
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), default="microsoft")
    stable_message_id: Mapped[str] = mapped_column(String(512), index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(512))
    outcome: Mapped[str] = mapped_column(String(32), default=OUTCOME_PENDING, index=True)
    skip_reason: Mapped[str | None] = mapped_column(String(64))
    folder_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
