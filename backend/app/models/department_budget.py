"""Department-level budget envelopes for Team Expenses."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DepartmentBudget(Base):
    __tablename__ = "department_budgets"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "department",
            "gl_ledger",
            "period_kind",
            "period_key",
            name="uq_department_budget_period",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    department: Mapped[str] = mapped_column(String(255), index=True)
    gl_ledger: Mapped[str] = mapped_column(String(255), default="", server_default="")
    period_kind: Mapped[str] = mapped_column(String(16))
    period_key: Mapped[str] = mapped_column(String(32))
    allocated: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
