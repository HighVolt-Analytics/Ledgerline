"""Daily reconciliation ORM model."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DailyReconciliation(Base):
    __tablename__ = "daily_reconciliations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    total_invoices: Mapped[int] = mapped_column(Integer, default=0)
    total_ap_credits: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    total_debits: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    total_credits: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    is_balanced: Mapped[bool] = mapped_column(Boolean, default=False)
    halted: Mapped[bool] = mapped_column(Boolean, default=False)
    halt_reason: Mapped[str | None] = mapped_column(Text)
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
