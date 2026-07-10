"""Minimum viable chart of accounts seeded for new tenants."""

from __future__ import annotations

from app.schemas.rule_book_config import ChartOfAccountEntry, PostingDefaults

SALES_RECEIVABLE_ACCOUNT = "Accounts Receivable"
SALES_TAX_ACCOUNT = "Tax Collected"
GENERIC_EXPENSE_ACCOUNT = "Operating Expenses"
GENERIC_REVENUE_ACCOUNT = "Sales Revenue"


def build_starter_chart_of_accounts(
    country_code: str | None,
    *,
    posting_defaults: PostingDefaults | None = None,
) -> list[ChartOfAccountEntry]:
    """Build starter COA aligned with jurisdiction posting defaults and sales pipeline labels."""
    posting = posting_defaults or PostingDefaults.for_country(country_code)
    return [
        ChartOfAccountEntry(code="1200", name=SALES_RECEIVABLE_ACCOUNT, type="Asset"),
        ChartOfAccountEntry(code="1400", name=posting.tax_account, type="Asset"),
        ChartOfAccountEntry(code="2000", name=posting.payable_account, type="Liability"),
        ChartOfAccountEntry(code="2300", name=SALES_TAX_ACCOUNT, type="Liability"),
        ChartOfAccountEntry(code="4100", name=GENERIC_REVENUE_ACCOUNT, type="Revenue"),
        ChartOfAccountEntry(code="6100", name=GENERIC_EXPENSE_ACCOUNT, type="Expense"),
        ChartOfAccountEntry(code="9999", name=posting.fallback_account, type="Liability"),
    ]
