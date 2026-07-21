"""Persisted Xero tracking category / option rows."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

SOURCE_SYSTEM_XERO = "xero"


class XeroTrackingCategory(Base):
    __tablename__ = "xero_tracking_categories"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "xero_tenant_id",
            "xero_tracking_category_id",
            "option_external_id",
            name="uq_xero_tracking_categories_option",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    accounting_integration_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_integrations.id", ondelete="CASCADE"),
        index=True,
    )
    xero_tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    xero_tracking_category_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str | None] = mapped_column(String(32))
    option_external_id: Mapped[str | None] = mapped_column(String(128), index=True)
    option_name: Mapped[str | None] = mapped_column(String(255))
    option_status: Mapped[str | None] = mapped_column(String(32))
    source_system: Mapped[str] = mapped_column(String(32), default=SOURCE_SYSTEM_XERO)
    sync_status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
