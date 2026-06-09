"""Low-confidence vendor detections awaiting registration."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PendingVendor(Base):
    __tablename__ = "pending_vendors"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organisations.id"), index=True)
    detected_name: Mapped[str] = mapped_column(String(255))
    detected_abn: Mapped[str | None] = mapped_column(String(11))
    detected_address: Mapped[str | None] = mapped_column(String(500))
    source_invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"),
        index=True,
    )
    confidence: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    promoted_master_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
