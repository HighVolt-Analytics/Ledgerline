from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_auth_context, get_db, AuthContext
from app.schemas.common import ApiEnvelope
from app.schemas.dashboard import ActivityItem, DashboardOverview, DashboardStats, NavBadges
from app.services.dashboard_service import (
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
    return ApiEnvelope(data=await build_nav_badges(db, org_id=ctx.org_id))


@router.get("/stats", response_model=ApiEnvelope[DashboardStats])
async def stats(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[DashboardStats]:
    """Aggregate KPI counters for dashboard cards and layout badges."""
    return ApiEnvelope(data=await build_stats(db, org_id=ctx.org_id))


@router.get("/overview", response_model=ApiEnvelope[DashboardOverview])
async def overview(
    activity_limit: int = Query(8, ge=1, le=50),
    month: str | None = Query(
        None,
        description="Period as YYYY-MM (defaults to current month)",
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
    ),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[DashboardOverview]:
    """Full dashboard payload (stats, activity, charts) in one request."""
    return ApiEnvelope(
        data=await build_overview(
            db,
            org_id=ctx.org_id,
            activity_limit=activity_limit,
            month=month,
        )
    )


@router.get("/activity", response_model=ApiEnvelope[list[ActivityItem]])
async def activity(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[list[ActivityItem]]:
    return ApiEnvelope(data=await fetch_activity(db, limit, org_id=ctx.org_id))
