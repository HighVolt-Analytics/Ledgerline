"""Fiscal period lock — every posting/reversal must land in an open period."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fiscal_period import FiscalPeriod, FiscalPeriodStatus


class PeriodClosedError(Exception):
    """Raised when a posting/reversal date falls in a closed fiscal period."""

    def __init__(self, tenant_id: uuid.UUID, entry_date: date, period: FiscalPeriod) -> None:
        self.tenant_id = tenant_id
        self.entry_date = entry_date
        self.period = period
        super().__init__(
            f"Fiscal period {period.period_start}..{period.period_end} covering "
            f"{entry_date} is closed"
        )


async def ensure_period_open(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    entry_date: date,
) -> None:
    """Raise PeriodClosedError if `entry_date` falls in a CLOSED period.

    No matching row = open by default.
    """
    stmt = select(FiscalPeriod).where(
        FiscalPeriod.tenant_id == tenant_id,
        FiscalPeriod.status == FiscalPeriodStatus.CLOSED.value,
        FiscalPeriod.period_start <= entry_date,
        FiscalPeriod.period_end >= entry_date,
    )
    period = (await session.execute(stmt)).scalars().first()
    if period is not None:
        raise PeriodClosedError(tenant_id, entry_date, period)


async def list_periods(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[FiscalPeriod]:
    stmt = (
        select(FiscalPeriod)
        .where(FiscalPeriod.tenant_id == tenant_id)
        .order_by(FiscalPeriod.period_start.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def close_period(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    period_start: date,
    period_end: date,
    closed_by: int | None,
) -> FiscalPeriod:
    if period_end < period_start:
        raise ValueError("period_end must be on or after period_start")

    existing = (
        await session.execute(
            select(FiscalPeriod).where(
                FiscalPeriod.tenant_id == tenant_id,
                FiscalPeriod.period_start == period_start,
                FiscalPeriod.period_end == period_end,
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.status = FiscalPeriodStatus.CLOSED.value
        existing.closed_at = now
        existing.closed_by = closed_by
        await session.flush()
        return existing

    period = FiscalPeriod(
        tenant_id=tenant_id,
        period_start=period_start,
        period_end=period_end,
        status=FiscalPeriodStatus.CLOSED.value,
        closed_at=now,
        closed_by=closed_by,
    )
    session.add(period)
    await session.flush()
    return period


async def reopen_period(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    period_id: int,
    *,
    reopened_by: int | None,
) -> FiscalPeriod:
    period = (
        await session.execute(
            select(FiscalPeriod).where(
                FiscalPeriod.id == period_id,
                FiscalPeriod.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if period is None:
        raise ValueError("Fiscal period not found")
    period.status = FiscalPeriodStatus.OPEN.value
    period.reopened_at = datetime.now(timezone.utc)
    period.reopened_by = reopened_by
    await session.flush()
    return period
