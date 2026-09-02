"""Rolling monthly DPO + straight-through % for the CFO trends panel."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.schemas.process_efficiency_trends import (
    ProcessEfficiencyTrendPoint,
    ProcessEfficiencyTrendsDashboard,
    ProcessEfficiencyTrendsMeta,
    ProcessEfficiencyTrendsSummary,
)
from app.services.reports.cfo_efficiency_assumptions import TOUCHLESS_TARGET_PCT
from app.services.reports.dashboard_period import _MONTH_NAMES, _subtract_months
from app.services.reports.dashboard_service import _institution_today, _month_end
from app.services.reports.exception_status_catalog_builders import process_efficiency_slice
from app.services.reports.position_liquidity_service import _compute_dpo
from app.tenant_settings import tenant_currency

_TREND_MONTHS = 12


def _month_label(month_start: date, *, span_years: bool) -> str:
    name = _MONTH_NAMES[month_start.month]
    if span_years:
        return f"{name} '{str(month_start.year)[-2:]}"
    return name


def _rolling_month_windows(as_of: date, months: int = _TREND_MONTHS) -> list[tuple[date, date, str]]:
    """Oldest → newest calendar months ending at as_of."""
    anchors = [_subtract_months(as_of, offset) for offset in range(months - 1, -1, -1)]
    span_years = len({anchor.year for anchor in anchors}) > 1
    windows: list[tuple[date, date, str]] = []
    for anchor in anchors:
        start = date(anchor.year, anchor.month, 1)
        end = as_of if anchor.year == as_of.year and anchor.month == as_of.month else _month_end(start)
        windows.append((start, end, _month_label(start, span_years=span_years)))
    return windows


async def _month_point(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    start: date,
    end: date,
    label: str,
    base: str,
) -> ProcessEfficiencyTrendPoint:
    dpo = await _compute_dpo(db, tenant_id, start, end, base=base)
    efficiency = await process_efficiency_slice(db, tenant_id, start, end)
    return ProcessEfficiencyTrendPoint(
        label=label,
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        dpo_days=dpo,
        stp_pct=efficiency.stp_pct,
    )


async def build_process_efficiency_trends_dashboard(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    environment_label: str | None = None,
    period: str | None = None,  # accepted for API symmetry; chart window is always rolling 12 months
) -> ProcessEfficiencyTrendsDashboard:
    del period
    tenant = await db.get(Tenant, tenant_id)
    as_of = await _institution_today(db, tenant_id)
    base = tenant_currency(tenant)
    windows = _rolling_month_windows(as_of)
    point_list: list[ProcessEfficiencyTrendPoint] = []
    for start, end, label in windows:
        point_list.append(
            await _month_point(
                db,
                tenant_id,
                start=start,
                end=end,
                label=label,
                base=base,
            )
        )
    months_with_dpo = sum(1 for point in point_list if point.dpo_days is not None)
    months_with_stp = sum(1 for point in point_list if point.stp_pct is not None)
    latest = point_list[-1] if point_list else None
    window_start = windows[0][0]
    window_end = windows[-1][1]
    period_label = (
        f"Rolling 12 months to {as_of.day} {_MONTH_NAMES[as_of.month]} {as_of.year}"
    )
    notes = [
        f"All amounts {base}, consolidated.",
        "Chart window is always the last 12 calendar months (independent of dashboard period filter).",
        "DPO (days) reuses the Position & Liquidity definition: average AP balance ÷ purchases × days in month.",
        "Straight-through % reuses Process Efficiency (no manual field edits or approval holds on posted invoices).",
        f"STP target {TOUCHLESS_TARGET_PCT}% is a platform constant (not yet tenant-configurable).",
        "Partial current month uses month-to-date for both series.",
    ]
    return ProcessEfficiencyTrendsDashboard(
        meta=ProcessEfficiencyTrendsMeta(
            currency=base,
            period_label=period_label,
            as_of=as_of.isoformat(),
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            environment_label=environment_label,
            notes=notes,
        ),
        points=point_list,
        summary=ProcessEfficiencyTrendsSummary(
            stp_target_pct=TOUCHLESS_TARGET_PCT,
            latest_dpo_days=latest.dpo_days if latest else None,
            latest_stp_pct=latest.stp_pct if latest else None,
            months_with_dpo=months_with_dpo,
            months_with_stp=months_with_stp,
        ),
    )
