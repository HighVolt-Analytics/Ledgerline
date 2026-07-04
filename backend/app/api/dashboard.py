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
    params: Annotated[DashboardOverviewRequest, Query()],
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[DashboardOverview]:
    """Full dashboard payload (stats, activity, charts) in one request."""
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
    params: Annotated[DashboardActivityRequest, Query()],
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[ActivityItem]]:
    return ApiEnvelope(
        data=await fetch_activity(db, params.limit, tenant_id=ctx.tenant_id)
    )
