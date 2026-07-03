"""Global credit and Azure unit-pricing settings (singleton row)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PlatformCreditSettings(Base):
    __tablename__ = "platform_credit_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    credits_per_page: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    universal_credits_per_page: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    topup_factor_in: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("1"))
    topup_factor_sg: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("10"))
    topup_factor_au: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("5"))
    azure_di_prebuilt_per_1000_pages_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("10.00")
    )
    azure_di_read_per_1000_pages_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("1.50")
    )
    azure_foundry_input_per_1m_tokens_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("2.50")
    )
    azure_foundry_output_per_1m_tokens_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("10.00")
    )
    azure_openai_mini_input_per_1m_tokens_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0.15")
    )
    azure_openai_mini_output_per_1m_tokens_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0.60")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
