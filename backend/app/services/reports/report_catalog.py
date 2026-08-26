"""Seed catalogue of named reports — append a definition to add a report."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_report_favourite import UserReportFavourite
from app.schemas.report_catalog import ReportCatalogItem, ReportCategory


class UnknownReportId(LookupError):
    """Raised when a report_id is not in the seed catalogue."""


class UnknownReportIds(ValueError):
    """Raised when a favourites payload contains unknown report ids (HTTP 422)."""


@dataclass(frozen=True)
class ReportDefinition:
    id: str
    name: str
    description: str
    category: ReportCategory
    supports_compare: bool = False


REPORT_DEFINITIONS: tuple[ReportDefinition, ...] = (
    ReportDefinition(
        id="aged-payables",
        name="Aged Payables",
        description="Outstanding AP remaining (control-account journals) as of period end, with invoice amount, amount paid, days overdue, and Current / 1–30 / 31–60 / 61–90 / 90+ buckets. Zero-balance invoices are omitted.",
        category="payables_receivables",
    ),
    ReportDefinition(
        id="payment-schedule",
        name="Payment Schedule",
        description="Plan a payment run. Amount Due is posted AP remaining. Timing compares due date to the as-at date (OVERDUE / due within 7 days / upcoming).",
        category="payables_receivables",
    ),
    ReportDefinition(
        id="invoice-register",
        name="Invoice Register",
        description="The source of truth for payables as of the period end. Vendor Spend, AP Aging and Payment Schedule read from here. Custom range still filters by invoice date.",
        category="transactions",
    ),
    ReportDefinition(
        id="vendor-spend-summary",
        name="Vendor Spend Summary",
        description="Totals per vendor from Invoice Register. Vendor names must match exactly. This Month / Quarter are as of period end; Custom still filters by invoice date.",
        category="payables_receivables",
    ),
    ReportDefinition(
        id="cash-forecast",
        name="Cash Forecast",
        description="Remaining posted AP due by date. Employee reimbursements are not included yet.",
        category="transactions",
    ),
    ReportDefinition(
        id="budget-variance",
        name="Budget vs Actual",
        description="Variance and utilisation by department / project / category. This Month / Quarter include GL budgets dated on or before period end. Committed = approved-but-not-yet-spent (in-flight Team Expense claims only).",
        category="budgets_performance",
        supports_compare=True,
    ),
    ReportDefinition(
        id="advance-reconciliation",
        name="Advance Reconciliation",
        description="Employee Staff Advance taken, used, outstanding, and available float.",
        category="transactions",
    ),
    ReportDefinition(
        id="advance-aging",
        name="Advance Aging",
        description="Unsettled advances bucketed by age from date issued. Chase the 60+ columns at close.",
        category="payables_receivables",
    ),
    ReportDefinition(
        id="expense-claims-register",
        name="Expense Claims Register",
        description="Every claim line. Feeds Advance Reconciliation and Reimbursement Due. This Month / Quarter are as of period end.",
        category="transactions",
    ),
    ReportDefinition(
        id="reimbursement-due",
        name="Reimbursement Due",
        description="Net owed to employees from Advance Reconciliation (Co. owes) and out-of-pocket claims not against advance.",
        category="transactions",
    ),
    ReportDefinition(
        id="missing-documents",
        name="Missing Documents",
        description="Anything expected-but-not-attached. This Month / Quarter are as of period end.",
        category="transactions",
    ),
    ReportDefinition(
        id="claim-status",
        name="Expense Claim Status",
        description="Tracks employee claims from draft/submission through approval and reimbursement.",
        category="transactions",
    ),
    ReportDefinition(
        id="policy-exceptions",
        name="Policy Exceptions",
        description="Open Team Expense policy failures (VR-TE04/05/08/09/10/11). Receipt gaps stay on Missing Documents.",
        category="transactions",
    ),
    ReportDefinition(
        id="invoice-exception",
        name="Invoice Exception",
        description="Fraud indicators and validation: potential duplicates, Purchase PO mismatch, and bank-detail-change documents. Non-PO invoices are omitted from the PO check.",
        category="payables_receivables",
    ),
    ReportDefinition(
        id="process-efficiency",
        name="Invoice Processing Efficiency",
        description="Speed, automation and operational efficiency across invoice-to-pay. Target and cost per invoice stay blank until those registers exist.",
        category="budgets_performance",
    ),
    ReportDefinition(
        id="control-centre",
        name="Control Centre",
        description="Prioritized action queue of exceptions, overdue items, and upcoming risks.",
        category="exceptions_controls",
    ),
)

# Catalog ids whose xlsx export uses the styled Team Expense workbook path.
TE_XLSX_KIND_BY_ID: dict[str, str] = {
    "advance-reconciliation": "advance-settlement",
    "advance-aging": "advance-aging",
    "expense-claims-register": "expense-claims-register",
    "reimbursement-due": "reimbursement-due",
    "missing-documents": "missing-documents",
}

CATALOG_BY_ID: dict[str, ReportDefinition] = {item.id: item for item in REPORT_DEFINITIONS}


def get_report_or_raise(report_id: str) -> ReportDefinition:
    definition = CATALOG_BY_ID.get(report_id)
    if definition is None:
        raise UnknownReportId(f"Unknown report: {report_id}")
    return definition


def catalog_items() -> list[ReportCatalogItem]:
    return [
        ReportCatalogItem(
            id=item.id,
            name=item.name,
            description=item.description,
            category=item.category,
            supports_compare=item.supports_compare,
        )
        for item in REPORT_DEFINITIONS
    ]


def validate_favourite_ids(report_ids: list[str]) -> list[str]:
    unknown = [rid for rid in report_ids if rid not in CATALOG_BY_ID]
    if unknown:
        raise UnknownReportIds(f"Unknown report_id(s): {', '.join(unknown)}")
    seen: list[str] = []
    for rid in report_ids:
        if rid not in seen:
            seen.append(rid)
    return seen


async def list_favourite_ids(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: int | None,
) -> list[str]:
    if user_id is None:
        return []
    rows = (
        await db.execute(
            select(UserReportFavourite.report_id).where(
                UserReportFavourite.tenant_id == tenant_id,
                UserReportFavourite.user_id == user_id,
            )
        )
    ).scalars().all()
    return [rid for rid in rows if rid in CATALOG_BY_ID]


async def replace_favourite_ids(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: int,
    report_ids: list[str],
) -> list[str]:
    wanted = validate_favourite_ids(report_ids)
    await db.execute(
        delete(UserReportFavourite).where(
            UserReportFavourite.tenant_id == tenant_id,
            UserReportFavourite.user_id == user_id,
        )
    )
    for report_id in wanted:
        db.add(
            UserReportFavourite(
                tenant_id=tenant_id,
                user_id=user_id,
                report_id=report_id,
            )
        )
    await db.flush()
    return wanted
