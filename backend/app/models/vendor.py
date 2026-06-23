"""Approved vendor registry for email routing and ABN trust."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class VendorRegistry(Base):
    __tablename__ = "vendor_registry"
    __table_args__ = (UniqueConstraint("tenant_id", "vendor_slug", name="uq_vendor_tenant_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tenants.id"), index=True)
    vendor_slug: Mapped[str] = mapped_column(String(100), index=True)
    vendor_name: Mapped[str] = mapped_column(String(255))
    sender_pattern: Mapped[str] = mapped_column(String(255), index=True)
    abn: Mapped[str | None] = mapped_column(String(11))
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
