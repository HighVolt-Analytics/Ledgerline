"""Deduplicate processed Xero webhook deliveries."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class XeroWebhookEvent(Base):
    __tablename__ = "xero_webhook_events"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_xero_webhook_events_event_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_key: Mapped[str] = mapped_column(String(255), index=True)
    xero_tenant_id: Mapped[str | None] = mapped_column(String(128), index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    event_category: Mapped[str | None] = mapped_column(String(64))
    event_type: Mapped[str | None] = mapped_column(String(64))
    payload_json: Mapped[str | None] = mapped_column(Text)
    signature_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
