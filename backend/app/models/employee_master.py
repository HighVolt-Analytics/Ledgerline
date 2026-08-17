"""Org-scoped employee master records for team expense validation."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database import Base


class EmployeeMasterRecord(Base):
    __tablename__ = "employee_masters"
    __table_args__ = (
        UniqueConstraint("tenant_id", "master_id", name="uq_employee_master_tenant_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tenants.id"), index=True)
    master_id: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    whatsapp_number: Mapped[str] = mapped_column(String(32), default="")
    whatsapp_number_2: Mapped[str] = mapped_column(String(32), default="")
    viber_number: Mapped[str | None] = mapped_column(String(32))
    date_of_joining: Mapped[str] = mapped_column(String(32), default="")
    department: Mapped[str] = mapped_column(String(255), default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    division: Mapped[str] = mapped_column(String(255), default="")
    supervisor_1: Mapped[str] = mapped_column(String(255), default="")
    supervisor_2: Mapped[str] = mapped_column(String(255), default="")
    bank: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    spending_limits: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    advance_parent_ledger: Mapped[str] = mapped_column(String(255), default="")
    advance_sub_ledger: Mapped[str] = mapped_column(String(255), default="")
    ytd_spent: Mapped[float] = mapped_column(Float, default=0)
    mtd_spent: Mapped[float] = mapped_column(Float, default=0)
    qtd_spent: Mapped[float] = mapped_column(Float, default=0)
    claim_count: Mapped[int] = mapped_column(Integer, default=0)
    last_claim: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(50), default="")
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
