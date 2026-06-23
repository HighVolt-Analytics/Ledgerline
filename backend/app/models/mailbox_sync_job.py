"""Background job: import historical mailbox messages from a date range."""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, func, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


class MailboxSyncJob(Base):
    __tablename__ = "mailbox_sync_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tenants.id"), index=True)
    mailbox_id: Mapped[int] = mapped_column(
        ForeignKey("connected_mailboxes.id", ondelete="CASCADE"),
        index=True,
    )
    from_date: Mapped[date] = mapped_column(Date)
    to_date: Mapped[date] = mapped_column(Date)
    mark_processed: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default=STATUS_QUEUED, index=True)
    messages_scanned: Mapped[int] = mapped_column(Integer, default=0)
    attachments_ingested: Mapped[int] = mapped_column(Integer, default=0)
    messages_skipped: Mapped[int] = mapped_column(Integer, default=0)
    invoices_processed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(String(2000))
    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
