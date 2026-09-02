"""Budget, concentration & risk — FY budget encumbrance + vendor spend for CFO dashboard."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.invoice import Invoice
from app.models.payment import Payment, PaymentStatus
from app.models.tenant import Tenant
from app.models.vendor_master import VendorMasterRecord
from app.schemas.budget_concentration_risk import (
    BudgetConcentrationRiskDashboard,
    BudgetConcentrationRiskMeta,
    BudgetDepartmentRow,
    BudgetEncumbranceSummary,
    VendorConcentrationRow,
    VendorConcentrationSummary,
)
from app.services.master_data.department_budget_service import list_department_budgets
from app.services.reports.dashboard_service import _institution_today
from app.services.reports.exception_status_catalog_builders import (
    _looks_like_bank_change_document,
    _parse_money,
)
from app.services.reports.payables_catalog_builders import (
    _group_invoice_payments,
    _vendor_group_key,
    ap_route_clause,
    build_vendor_spend_summary,
)
from app.services.reports.dashboard_period import resolve_dashboard_period
from app.services.reports.position_liquidity_service import _vendor_concentration
from app.services.reports.report_catalog import CATALOG_BY_ID
from app.services.reports.statement_builders import _build_budget_variance
from app.tenant_settings import tenant_currency

_ZERO = Decimal("0.00")
_TOP_VENDOR_LIMIT = 10
_UNASSIGNED_DEPARTMENT = "Unassigned"


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator <= 0:
        return None
    return _quantize((numerator / denominator) * Decimal("100"))


async def _department_owner_map(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> dict[str, str]:
    owners: dict[str, str] = {}
    for bud in await list_department_budgets(db, tenant_id):
        note = (bud.notes or "").strip()
        if not note:
            continue
        for key in (
            (bud.department or "").strip(),
            (bud.gl_ledger or "").strip(),
        ):
            if key and key not in owners:
                owners[key] = note
    return owners


def _parse_budget_summary(
    preview,
) -> tuple[list[BudgetDepartmentRow], BudgetEncumbranceSummary, str]:
    dept_idx = preview.columns.index("Department / Project")
    cat_idx = preview.columns.index("Category")
    budget_idx = preview.columns.index("Budget")
    committed_idx = preview.columns.index("Committed")
    actual_idx = preview.columns.index("Actual")

    grouped: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"budget": _ZERO, "actual": _ZERO, "committed": _ZERO}
    )
    has_department_labels = False
    summary = BudgetEncumbranceSummary()

    for row in preview.rows:
        if not row.emphasize:
            dept = (row.cells[dept_idx] or "").strip()
            category = (row.cells[cat_idx] or "").strip()
            if dept:
                has_department_labels = True
            name = dept or category or _UNASSIGNED_DEPARTMENT
            grouped[name]["budget"] += _parse_money(row.cells[budget_idx])
            grouped[name]["actual"] += _parse_money(row.cells[actual_idx])
            grouped[name]["committed"] += _parse_money(row.cells[committed_idx])
            continue
        if (row.cells[0] or "").strip().upper() != "TOTAL":
            continue
        budget = _parse_money(row.cells[budget_idx])
        committed = _parse_money(row.cells[committed_idx])
        actual = _parse_money(row.cells[actual_idx])
        remaining = budget - actual - committed
        summary = BudgetEncumbranceSummary(
            budget=_quantize(budget),
            actual=_quantize(actual),
            committed=_quantize(committed),
            remaining=_quantize(remaining),
            utilisation_pct=_pct(actual, budget),
        )

    group_label = "department" if has_department_labels else "GL account"
    return (
        [
            BudgetDepartmentRow(
                name=name,
                budget=_quantize(values["budget"]),
                actual=_quantize(values["actual"]),
                committed=_quantize(values["committed"]),
            )
            for name, values in grouped.items()
        ],
        summary,
        group_label,
    )


async def _department_rows(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
) -> tuple[list[BudgetDepartmentRow], BudgetEncumbranceSummary, str]:
    preview = await _build_budget_variance(
        db,
        tenant_id,
        CATALOG_BY_ID["budget-variance"],
        start,
        end,
        compare=False,
        as_of=True,
    )
    if not preview.rows:
        return [], BudgetEncumbranceSummary(), "department / GL"

    rows, summary, group_label = _parse_budget_summary(preview)
    owners = await _department_owner_map(db, tenant_id)
    enriched = [
        row.model_copy(update={"owner": owners.get(row.name, "")})
        for row in rows
    ]
    enriched.sort(key=lambda row: (row.budget, row.name), reverse=True)
    return enriched, summary, group_label


def _vendor_master_lookup(
    masters: list[VendorMasterRecord],
) -> dict[str, VendorMasterRecord]:
    out: dict[str, VendorMasterRecord] = {}
    for master in masters:
        out[master.name.strip().casefold()] = master
        for alias in master.aliases or []:
            token = str(alias or "").strip()
            if token:
                out[token.casefold()] = master
    return out


def _is_contracted(master: VendorMasterRecord | None) -> bool:
    if master is None:
        return False
    if master.confirmed_at is not None:
        return True
    status = (master.status or "").strip().lower()
    return status in {"approved", "active", "confirmed", "registered"}


def _risk_level(*, bank_change: bool, po_backed_pct: Decimal | None) -> str:
    if bank_change:
        return "High"
    if po_backed_pct is not None and po_backed_pct < Decimal("50"):
        return "Medium"
    return "Low"


async def _vendor_rows(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    start: date,
    end: date,
    *,
    base: str,
) -> list[VendorConcentrationRow]:
    preview = await build_vendor_spend_summary(
        db,
        tenant_id,
        CATALOG_BY_ID["vendor-spend-summary"],
        start,
        end,
        as_of=True,
    )
    invoiced_idx = preview.columns.index("Total Invoiced")
    count_idx = preview.columns.index("# Invoices")
    ranked: list[tuple[str, Decimal, int]] = []
    for row in preview.rows:
        if row.emphasize:
            continue
        vendor = row.cells[0]
        if vendor.upper() == "TOTAL":
            continue
        ranked.append(
            (
                vendor,
                _parse_money(row.cells[invoiced_idx]),
                int(row.cells[count_idx] or "0"),
            )
        )
    ranked.sort(key=lambda item: item[1], reverse=True)
    top = ranked[:_TOP_VENDOR_LIMIT]
    if not top:
        return []

    pay = aliased(Payment)
    stmt = (
        select(Invoice, pay)
        .outerjoin(
            pay,
            (pay.invoice_id == Invoice.id) & (pay.tenant_id == tenant_id),
        )
        .where(
            Invoice.tenant_id == tenant_id,
            ap_route_clause(),
            Invoice.invoice_date.is_not(None),
            Invoice.invoice_date >= start,
            Invoice.invoice_date <= end,
        )
    )
    stats: dict[str, dict[str, Decimal | int | bool]] = defaultdict(
        lambda: {
            "invoice_count": 0,
            "po_count": 0,
            "cycle_total_days": 0,
            "cycle_count": 0,
            "bank_change": False,
        }
    )
    for invoice, payments in _group_invoice_payments((await db.execute(stmt)).all()):
        _, display = _vendor_group_key(invoice.vendor)
        bucket = stats[display]
        bucket["invoice_count"] = int(bucket["invoice_count"]) + 1
        if (invoice.po_reference or "").strip():
            bucket["po_count"] = int(bucket["po_count"]) + 1
        if _looks_like_bank_change_document(invoice):
            bucket["bank_change"] = True
        invoice_day = invoice.invoice_date
        if invoice_day is None:
            continue
        for payment in payments:
            if payment.status != PaymentStatus.PAID or payment.paid_date is None:
                continue
            paid_day = payment.paid_date.date()
            days = (paid_day - invoice_day).days
            if days >= 0:
                bucket["cycle_total_days"] = int(bucket["cycle_total_days"]) + days
                bucket["cycle_count"] = int(bucket["cycle_count"]) + 1
                break

    rows: list[VendorConcentrationRow] = []
    for name, spend, invoice_count in top:
        detail = stats.get(name, {})
        po_count = int(detail.get("po_count", 0))
        inv_count = int(detail.get("invoice_count", 0)) or invoice_count
        po_pct = _pct(Decimal(po_count), Decimal(inv_count)) if inv_count > 0 else None
        cycle_count = int(detail.get("cycle_count", 0))
        cycle_days = None
        if cycle_count > 0:
            cycle_days = _quantize(
                Decimal(str(detail.get("cycle_total_days", 0))) / Decimal(cycle_count)
            )
        bank_change = bool(detail.get("bank_change", False))
        rows.append(
            VendorConcentrationRow(
                name=name,
                spend=_quantize(spend),
                invoice_count=invoice_count,
                cycle_days=cycle_days,
                po_backed_pct=po_pct,
                risk_level=_risk_level(bank_change=bank_change, po_backed_pct=po_pct),
                bank_change_flag=bank_change,
            )
        )
    return rows


async def build_budget_concentration_risk_dashboard(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    environment_label: str | None = None,
    period: str | None = None,
) -> BudgetConcentrationRiskDashboard:
    tenant = await db.get(Tenant, tenant_id)
    base = tenant_currency(tenant)
    as_of = await _institution_today(db, tenant_id)
    period_start, period_end, period_label = resolve_dashboard_period(period, as_of)

    departments, budget_summary, group_label = await _department_rows(
        db, tenant_id, period_start, period_end
    )
    vendors = await _vendor_rows(
        db, tenant_id, period_start, period_end, base=base
    )
    top10_pct, non_po_pct = await _vendor_concentration(
        db, tenant_id, period_start, period_end, base=base
    )

    masters = (
        await db.execute(
            select(VendorMasterRecord).where(VendorMasterRecord.tenant_id == tenant_id)
        )
    ).scalars().all()
    master_by_name = _vendor_master_lookup(masters)
    contracted = sum(
        1
        for vendor in vendors
        if _is_contracted(master_by_name.get(vendor.name.casefold()))
    )
    high_risk = sum(1 for vendor in vendors if vendor.risk_level == "High")

    notes = [
        f"All amounts {base}, consolidated.",
        "Budget vs Actual chart reuses the Budget vs Actual report (department / GL rows).",
        "Committed = approved-but-not-yet-spent in-flight Team Expense claims only.",
        "Rows group by department label when present; otherwise by GL category.",
        "Vendor Spend Summary chart uses invoiced amounts for the selected period.",
        "PO reference % = invoices with a PO reference ÷ invoice count per vendor.",
        "Pay cycle = average days from invoice date to first paid payment.",
        "Bank detail change = DT-23 style documents flagged on the vendor bar.",
        "Vendor master registered = confirmed or approved vendor master among top 10.",
    ]
    coverage_gaps = [
        "department_owner: optional budget notes only — no dedicated owner register.",
        "vendor_contract_register: contracted count uses vendor-master confirmation only.",
        "no_gl_budgets: chart and encumbrance table are empty until GL budgets are configured.",
    ]

    return BudgetConcentrationRiskDashboard(
        meta=BudgetConcentrationRiskMeta(
            currency=base,
            period_label=period_label,
            as_of=as_of.isoformat(),
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            budget_group_label=group_label,
            environment_label=environment_label,
            coverage_gaps=coverage_gaps,
            notes=notes,
        ),
        departments=departments,
        budget_summary=budget_summary,
        vendors=vendors,
        vendor_summary=VendorConcentrationSummary(
            top10_concentration_pct=top10_pct,
            non_po_spend_pct=non_po_pct,
            contracted_in_top10=contracted,
            high_risk_count=high_risk,
        ),
    )
