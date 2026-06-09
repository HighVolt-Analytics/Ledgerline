"""Org-scoped employee master records for team expense validation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database import Base


class EmployeeMasterRecord(Base):
    __tablename__ = "employee_masters"
    __table_args__ = (
        UniqueConstraint("org_id", "master_id", name="uq_employee_master_org_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organisations.id"), index=True)
    master_id: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    whatsapp_number: Mapped[str] = mapped_column(String(32), default="")
    viber_number: Mapped[str | None] = mapped_column(String(32))
    bank: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    budget: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ytd_spent: Mapped[float] = mapped_column(Float, default=0)
    mtd_spent: Mapped[float] = mapped_column(Float, default=0)
    qtd_spent: Mapped[float] = mapped_column(Float, default=0)
    claim_count: Mapped[int] = mapped_column(Integer, default=0)
    last_claim: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
