from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_auth_context, get_db, AuthContext
from app.services.shared.currency import get_tenant_fx_rates, tenant_fx_rates_scope
from app.schemas.common import ApiEnvelope
from app.schemas.dashboard import ActivityItem, DashboardOverview, DashboardStats, NavBadges
from app.schemas.dashboard_api import DashboardActivityRequest, DashboardOverviewRequest
from app.schemas.position_liquidity import PositionLiquidityDashboard
from app.schemas.efficiency_automation import EfficiencyAutomationDashboard
from app.schemas.cash_liability_outlook import CashLiabilityOutlookDashboard
from app.schemas.budget_concentration_risk import BudgetConcentrationRiskDashboard
from app.schemas.cfo_alerts import CfoAlertsDashboard
from app.schemas.process_efficiency_trends import ProcessEfficiencyTrendsDashboard
from app.services.reports.dashboard_service import (
    build_nav_badges,
    build_overview,
    build_stats,
    fetch_activity,
)
from app.services.reports.position_liquidity_service import build_position_liquidity_dashboard
from app.services.reports.efficiency_automation_service import (
    build_efficiency_automation_dashboard,
)
from app.services.reports.cash_liability_outlook_service import (
    build_cash_liability_outlook_dashboard,
)
from app.services.reports.budget_concentration_risk_service import (
    build_budget_concentration_risk_dashboard,
)
from app.services.reports.cfo_alerts_service import build_cfo_alerts_dashboard
from app.services.reports.process_efficiency_trends_service import (
    build_process_efficiency_trends_dashboard,
)
from app.services.reports.dashboard_period import DEFAULT_DASHBOARD_PERIOD

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

DashboardPeriodQuery = Annotated[
    str | None,
    Query(
        description="Reporting window: fy_ytd (financial year YTD), mtd, fq_ytd (fiscal quarter YTD), r12",
    ),
]


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
    fx_rates = await get_tenant_fx_rates(db, ctx.tenant_id)
    with tenant_fx_rates_scope(fx_rates):
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
    fx_rates = await get_tenant_fx_rates(db, ctx.tenant_id)
    with tenant_fx_rates_scope(fx_rates):
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


@router.get("/position-liquidity", response_model=ApiEnvelope[PositionLiquidityDashboard])
async def position_liquidity(
    period: DashboardPeriodQuery = DEFAULT_DASHBOARD_PERIOD,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[PositionLiquidityDashboard]:
    """Dashboard Position & Liquidity KPI row — each figure reuses its detail report definition."""
    label = (
        ctx.tenant.name
        if ctx.tenant is not None and (ctx.tenant.name or "").strip()
        else ctx.tenant_slug
    )
    fx_rates = await get_tenant_fx_rates(db, ctx.tenant_id)
    with tenant_fx_rates_scope(fx_rates):
        return ApiEnvelope(
            data=await build_position_liquidity_dashboard(
                db,
                tenant_id=ctx.tenant_id,
                environment_label=label,
                period=period,
            )
        )


@router.get(
    "/efficiency-automation",
    response_model=ApiEnvelope[EfficiencyAutomationDashboard],
)
async def efficiency_automation(
    period: DashboardPeriodQuery = DEFAULT_DASHBOARD_PERIOD,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[EfficiencyAutomationDashboard]:
    """Dashboard Efficiency & Automation KPI row — reuses Process Efficiency / Missing Documents."""
    label = (
        ctx.tenant.name
        if ctx.tenant is not None and (ctx.tenant.name or "").strip()
        else ctx.tenant_slug
    )
    fx_rates = await get_tenant_fx_rates(db, ctx.tenant_id)
    with tenant_fx_rates_scope(fx_rates):
        return ApiEnvelope(
            data=await build_efficiency_automation_dashboard(
                db,
                tenant_id=ctx.tenant_id,
                environment_label=label,
                period=period,
            )
        )


@router.get(
    "/cash-liability-outlook",
    response_model=ApiEnvelope[CashLiabilityOutlookDashboard],
)
async def cash_liability_outlook(
    period: DashboardPeriodQuery = DEFAULT_DASHBOARD_PERIOD,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[CashLiabilityOutlookDashboard]:
    """Dashboard cash forecast + AP ageing — reuses Cash Forecast / Aged Payables definitions."""
    label = (
        ctx.tenant.name
        if ctx.tenant is not None and (ctx.tenant.name or "").strip()
        else ctx.tenant_slug
    )
    fx_rates = await get_tenant_fx_rates(db, ctx.tenant_id)
    with tenant_fx_rates_scope(fx_rates):
        return ApiEnvelope(
            data=await build_cash_liability_outlook_dashboard(
                db,
                tenant_id=ctx.tenant_id,
                environment_label=label,
                period=period,
            )
        )


@router.get(
    "/budget-concentration-risk",
    response_model=ApiEnvelope[BudgetConcentrationRiskDashboard],
)
async def budget_concentration_risk(
    period: DashboardPeriodQuery = DEFAULT_DASHBOARD_PERIOD,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[BudgetConcentrationRiskDashboard]:
    """Dashboard budget encumbrance + vendor concentration — reuses Budget Variance / Vendor Spend."""
    label = (
        ctx.tenant.name
        if ctx.tenant is not None and (ctx.tenant.name or "").strip()
        else ctx.tenant_slug
    )
    return ApiEnvelope(
        data=await build_budget_concentration_risk_dashboard(
            db,
            tenant_id=ctx.tenant_id,
            environment_label=label,
            period=period,
        )
    )


@router.get(
    "/cfo-alerts",
    response_model=ApiEnvelope[CfoAlertsDashboard],
)
async def cfo_alerts(
    period: DashboardPeriodQuery = DEFAULT_DASHBOARD_PERIOD,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[CfoAlertsDashboard]:
    """Dashboard alerts — Control Centre rows plus KPI threshold breaches."""
    label = (
        ctx.tenant.name
        if ctx.tenant is not None and (ctx.tenant.name or "").strip()
        else ctx.tenant_slug
    )
    return ApiEnvelope(
        data=await build_cfo_alerts_dashboard(
            db,
            tenant_id=ctx.tenant_id,
            environment_label=label,
            period=period,
        )
    )


@router.get(
    "/process-efficiency-trends",
    response_model=ApiEnvelope[ProcessEfficiencyTrendsDashboard],
)
async def process_efficiency_trends(
    period: DashboardPeriodQuery = DEFAULT_DASHBOARD_PERIOD,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ApiEnvelope[ProcessEfficiencyTrendsDashboard]:
    """Rolling 12-month DPO + straight-through % — reuses Position & Liquidity / Process Efficiency."""
    label = (
        ctx.tenant.name
        if ctx.tenant is not None and (ctx.tenant.name or "").strip()
        else ctx.tenant_slug
    )
    fx_rates = await get_tenant_fx_rates(db, ctx.tenant_id)
    with tenant_fx_rates_scope(fx_rates):
        return ApiEnvelope(
            data=await build_process_efficiency_trends_dashboard(
                db,
                tenant_id=ctx.tenant_id,
                environment_label=label,
                period=period,
            )
        )
