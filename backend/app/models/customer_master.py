"""Org-scoped customer master records for sales detection."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database import Base


class CustomerMasterRecord(Base):
    __tablename__ = "customer_masters"
    __table_args__ = (
        UniqueConstraint("tenant_id", "master_id", name="uq_customer_master_tenant_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tenants.id"), index=True)
    master_id: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(255))
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    abn: Mapped[str] = mapped_column(String(11), default="")
    billing_address: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    default_ledger: Mapped[str] = mapped_column(String(255), default="")
    default_sub_ledger: Mapped[str] = mapped_column(String(255), default="")
    payment_terms: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(50), default="")
    registered_on: Mapped[str] = mapped_column(String(32), default="")
    total_revenue_ytd: Mapped[float] = mapped_column(Float, default=0)
    invoice_count: Mapped[int] = mapped_column(Integer, default=0)
    match_confidence: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
