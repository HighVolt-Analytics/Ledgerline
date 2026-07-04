"""Daily reconciliation list and detail queries."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reconciliation import DailyReconciliation
from app.schemas.reconciliation import ReconciliationResponse


async def list_daily_reconciliations(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
) -> list[ReconciliationResponse]:
    rows = (
        await db.execute(
            select(DailyReconciliation)
            .where(DailyReconciliation.tenant_id == tenant_id)
            .order_by(DailyReconciliation.date.desc())
        )
    ).scalars().all()
    return [ReconciliationResponse.model_validate(r) for r in rows]


async def get_daily_reconciliation(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    recon_date: date,
) -> ReconciliationResponse | None:
    row = (
        await db.execute(
            select(DailyReconciliation).where(
                DailyReconciliation.date == recon_date,
                DailyReconciliation.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        return None
    return ReconciliationResponse.model_validate(row)
