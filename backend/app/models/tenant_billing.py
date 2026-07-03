"""Per-tenant subscription plan and credit balance."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TenantBilling(Base):
    __tablename__ = "tenant_billing"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    plan: Mapped[str] = mapped_column(String(20), default="free", nullable=False)
    credit_balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    credits_per_page_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    billing_anchor_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_monthly_grant_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    enterprise_monthly_credits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
