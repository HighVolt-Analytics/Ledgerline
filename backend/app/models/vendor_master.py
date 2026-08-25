"""Org-scoped vendor master records for rule book detection."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database import Base


class VendorMasterRecord(Base):
    __tablename__ = "vendor_masters"
    __table_args__ = (
        UniqueConstraint("tenant_id", "master_id", name="uq_vendor_master_tenant_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tenants.id"), index=True)
    master_id: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(255))
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    abn: Mapped[str] = mapped_column(String(11), default="")
    billing_address: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    bank: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    default_ledger: Mapped[str] = mapped_column(String(255), default="")
    default_sub_ledger: Mapped[str] = mapped_column(String(255), default="")
    payment_terms: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(50), default="")
    registered_on: Mapped[str] = mapped_column(String(32), default="")
    total_spend_ytd: Mapped[float] = mapped_column(Float, default=0)
    invoice_count: Mapped[int] = mapped_column(Integer, default=0)
    match_confidence: Mapped[float] = mapped_column(Float, default=0)
    contact_email: Mapped[str] = mapped_column(String(255), default="")
    contact_phone: Mapped[str] = mapped_column(String(64), default="")
    confirmation_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
