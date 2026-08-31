"""Fiscal period lock — closed periods block new postings and reversals.

Absence of a row for a date = open. Rows are only created when a tenant
explicitly closes a period through the admin API, so this is a fully
non-breaking rollout: every existing tenant stays open on every date until
someone deliberately closes one.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FiscalPeriodStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class FiscalPeriod(Base):
    """A date range for a tenant, closed or (after being reopened) open again."""

    __tablename__ = "fiscal_periods"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "period_start", "period_end", name="uq_fiscal_periods_range"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(
        String(16),
        default=FiscalPeriodStatus.CLOSED.value,
        server_default=FiscalPeriodStatus.CLOSED.value,
        index=True,
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopened_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
