"""CFO alerts & threshold breaches — Control Centre rows + KPI covenant thresholds."""

from __future__ import annotations

import uuid
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.schemas.cfo_alerts import CfoAlertRow, CfoAlertsDashboard, CfoAlertsMeta, CfoAlertsSummary
from app.services.reports.budget_concentration_risk_service import (
    build_budget_concentration_risk_dashboard,
)
from app.services.reports.dashboard_service import _institution_today
from app.services.reports.efficiency_automation_service import build_efficiency_automation_dashboard
from app.services.reports.exception_status_catalog_builders import (
    _preview_maps,
    build_control_centre,
)
from app.services.reports.dashboard_period import resolve_dashboard_period
from app.services.reports.position_liquidity_service import build_position_liquidity_dashboard
from app.services.reports.report_catalog import CATALOG_BY_ID
from app.tenant_settings import tenant_currency

_ZERO = Decimal("0.00")
_SEVERITY_RANK = {"high": 0, "med": 1, "low": 2}


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _money(value: Decimal) -> str:
    return f"{_quantize(value):,.2f}"


def _priority_to_severity(priority: str) -> str:
    token = (priority or "").strip().casefold()
    if token in {"critical", "high"}:
        return "high"
    if token == "medium":
        return "med"
    return "low"


def _control_centre_alerts(preview) -> list[CfoAlertRow]:
    rows: list[CfoAlertRow] = []
    for item in _preview_maps(preview):
        module = (item.get("Module") or "").strip()
        amount = (item.get("Amount") or "").strip()
        status = (item.get("Status") or "").strip()
        owner = (item.get("Owner") or "").strip()
        action = (item.get("Recommended Action") or "").strip()
        age_due = (item.get("Age / Due") or "").strip()
        detail_parts = [p for p in (module, amount, status) if p]
        meta_parts = [p for p in (action, age_due, owner) if p]
        rows.append(
            CfoAlertRow(
                severity=_priority_to_severity(item.get("Priority", "")),
                title=(item.get("Alert") or "").strip() or "Open exception",
                detail=" · ".join(detail_parts),
                meta=" · ".join(meta_parts),
                module=module,
                source="control_centre",
            )
        )
    return rows


def _threshold_alerts(
  *,
    currency: str,
    liquidity,
    efficiency,
    budget_departments,
) -> list[CfoAlertRow]:
    rows: list[CfoAlertRow] = []
    lk = liquidity.kpis
    ek = efficiency.kpis

    if lk.overdue > _ZERO:
        rows.append(
            CfoAlertRow(
                severity="med",
                title="Overdue AP outstanding",
                detail=(
                    f"{_money(lk.overdue)} {currency} in Aged Payables past-due buckets "
                    f"(1–30 {_money(lk.overdue_1_30)} · 31–60 {_money(lk.overdue_31_60)} · "
                    f"61–90 {_money(lk.overdue_61_90)} · 90+ {_money(lk.overdue_90_plus)})"
                ),
                meta="Source: Aged Payables",
                module="Invoice-to-Pay",
                source="threshold",
            )
        )

    if (
        ek.touchless_processing_pct is not None
        and ek.touchless_target_pct is not None
        and ek.touchless_processing_pct < ek.touchless_target_pct
    ):
        rows.append(
            CfoAlertRow(
                severity="low",
                title="Touchless rate below target",
                detail=(
                    f"{ek.touchless_processing_pct}% vs {ek.touchless_target_pct}% target"
                ),
                meta="Source: Process Efficiency (STP proxy)",
                module="Automation",
                source="threshold",
            )
        )

    if lk.claims_pending_count > 0:
        rows.append(
            CfoAlertRow(
                severity="med",
                title="Claims pending approval",
                detail=(
                    f"{lk.claims_pending_count} claim(s) with Status/Reason != Approved"
                ),
                meta="Expense Claim Status report",
                module="Expenses",
                source="threshold",
            )
        )

    if ek.sync_dead_letter_count > 0:
        label = ek.sync_providers_label or "accounting sync"
        rows.append(
            CfoAlertRow(
                severity="low",
                title=f"{label} dead-letter queue",
                detail=(
                    f"{ek.sync_dead_letter_count} job(s) failed after retry — "
                    "review sync errors"
                ),
                meta=(
                    f"Sync success {ek.sync_success_pct}%"
                    if ek.sync_success_pct is not None
                    else "Sync success not available"
                ),
                module="Integrations",
                source="threshold",
            )
        )

    for dept in budget_departments:
        if dept.budget <= _ZERO or dept.actual <= dept.budget:
            continue
        utilised = _quantize((dept.actual / dept.budget) * Decimal("100"))
        rows.append(
            CfoAlertRow(
                severity="high",
                title=f"{dept.name} over budget",
                detail=(
                    f"Actual {_money(dept.actual)} vs budget {_money(dept.budget)} "
                    f"— {utilised}% utilised"
                    + (
                        f", {_money(dept.committed)} committed"
                        if dept.committed > _ZERO
                        else ""
                    )
                ),
                meta=f"Owner: {dept.owner}" if dept.owner else "Budget Variance FY window",
                module="Budget",
                source="threshold",
            )
        )

    return rows


def _bank_change_alerts(vendors, *, existing_titles: set[str]) -> list[CfoAlertRow]:
    rows: list[CfoAlertRow] = []
    for vendor in vendors:
        if not vendor.bank_change_flag:
            continue
        title = f"Vendor bank detail change — {vendor.name}"
        if title.casefold() in existing_titles:
            continue
        rows.append(
            CfoAlertRow(
                severity="high",
                title=title,
                detail=(
                    f"FY spend {_money(vendor.spend)} · "
                    f"{vendor.invoice_count} invoice(s) flagged"
                ),
                meta="Control: Bank change verification",
                module="Invoice-to-Pay",
                source="bank_change",
            )
        )
    return rows


def _sort_alerts(rows: list[CfoAlertRow]) -> list[CfoAlertRow]:
    return sorted(
        rows,
        key=lambda row: (
            _SEVERITY_RANK.get(row.severity, 9),
            row.title.casefold(),
        ),
    )


def _summarize(rows: list[CfoAlertRow]) -> CfoAlertsSummary:
    high = sum(1 for row in rows if row.severity == "high")
    med = sum(1 for row in rows if row.severity == "med")
    low = sum(1 for row in rows if row.severity == "low")
    return CfoAlertsSummary(
        active_count=len(rows),
        high_count=high,
        med_count=med,
        low_count=low,
    )


async def build_cfo_alerts_dashboard(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    environment_label: str | None = None,
    period: str | None = None,
) -> CfoAlertsDashboard:
    tenant = await db.get(Tenant, tenant_id)
    base = tenant_currency(tenant)
    as_of = await _institution_today(db, tenant_id)
    period_start, period_end, period_label = resolve_dashboard_period(period, as_of)

    control_preview = await build_control_centre(
        db,
        tenant_id,
        CATALOG_BY_ID["control-centre"],
        period_start,
        period_end,
        as_of=True,
    )
    liquidity = await build_position_liquidity_dashboard(
        db, tenant_id=tenant_id, environment_label=environment_label, period=period
    )
    efficiency = await build_efficiency_automation_dashboard(
        db, tenant_id=tenant_id, environment_label=environment_label, period=period
    )
    budget_risk = await build_budget_concentration_risk_dashboard(
        db, tenant_id=tenant_id, environment_label=environment_label, period=period
    )

    alerts = _control_centre_alerts(control_preview)
    existing_titles = {row.title.casefold() for row in alerts}
    alerts.extend(
        _threshold_alerts(
            currency=base,
            liquidity=liquidity,
            efficiency=efficiency,
            budget_departments=budget_risk.departments,
        )
    )
    alerts.extend(_bank_change_alerts(budget_risk.vendors, existing_titles=existing_titles))
    alerts = _sort_alerts(alerts)

    notes = [
        f"All amounts {base}, consolidated (except Position & Liquidity register tiles, "
        "which report native per-currency totals).",
        "Row-level alerts reuse Control Centre report definitions (overdue AP, advances >60d, "
        "budget forecast overrun, policy exceptions, invoice exceptions, missing receipts).",
        "Threshold breaches add KPI alerts: overdue Aged Payables balance, touchless target, "
        "claims with Status/Reason != Approved, sync dead-letter queue, and departments "
        "where actual > budget.",
        "Bank-change vendor flags come from invoice document detection (same as Vendor "
        "Concentration risk panel); omitted from Control Centre until a dedicated register exists.",
        f"Touchless target {efficiency.kpis.touchless_target_pct}% is a platform constant "
        "(not yet tenant-configurable).",
    ]
    coverage_gaps = [
        "insurance_expiry: not evaluated — no register wired.",
        "unsubstantiated_card_spend_aggregate: policy rows surface individually; no rolled-up card threshold.",
        "xero_dead_letter: generic sync dead-letter count only — provider-specific diagnostics not exposed.",
    ]

    return CfoAlertsDashboard(
        meta=CfoAlertsMeta(
            currency=base,
            period_label=period_label,
            as_of=as_of.isoformat(),
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            environment_label=environment_label,
            coverage_gaps=coverage_gaps,
            notes=notes,
        ),
        summary=_summarize(alerts),
        alerts=alerts,
    )
