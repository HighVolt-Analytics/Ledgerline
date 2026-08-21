from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_auth_context, get_db, AuthContext
from app.schemas.common import ApiEnvelope
from app.schemas.dashboard import ActivityItem, DashboardOverview, DashboardStats, NavBadges
from app.schemas.dashboard_api import DashboardActivityRequest, DashboardOverviewRequest
from app.services.reports.dashboard_service import (
    build_nav_badges,
    build_overview,
    build_stats,
    fetch_activity,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/badges", response_model=ApiEnvelope[NavBadges])
async def badges(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[NavBadges]:
    """Lightweight sidebar counters for layout navigation."""
    return ApiEnvelope(data=await build_nav_badges(db, tenant_id=ctx.tenant_id))


@router.get("/stats", response_model=ApiEnvelope[DashboardStats])
async def stats(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[DashboardStats]:
    """Aggregate KPI counters for dashboard cards and layout badges."""
    return ApiEnvelope(data=await build_stats(db, tenant_id=ctx.tenant_id))


@router.get("/overview", response_model=ApiEnvelope[DashboardOverview])
async def overview(
    activity_limit: Annotated[int, Query(ge=1, le=50)] = 8,
    month: Annotated[
        str | None,
        Query(
            description="Period as YYYY-MM (defaults to current month)",
            pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        ),
    ] = None,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[DashboardOverview]:
    """Full dashboard payload for the page (stats, vendors, forecast, panels).

    Activity, anomalies, mailbox breakdown, and sparkline series are not
    computed here — they are unused on Dashboard. Use ``GET /activity``
    when recent events are needed.
    """
    params = DashboardOverviewRequest(activity_limit=activity_limit, month=month)
    return ApiEnvelope(
        data=await build_overview(
            db,
            tenant_id=ctx.tenant_id,
            activity_limit=params.activity_limit,
            month=params.month,
        )
    )


@router.get("/activity", response_model=ApiEnvelope[list[ActivityItem]])
async def activity(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[ActivityItem]]:
    params = DashboardActivityRequest(limit=limit)
    return ApiEnvelope(
        data=await fetch_activity(db, params.limit, tenant_id=ctx.tenant_id)
    )
