"""Minimum viable chart of accounts seeded for new tenants."""

from __future__ import annotations

from app.schemas.rule_book_config import ChartOfAccountEntry, PostingDefaults

SALES_RECEIVABLE_ACCOUNT = "Accounts Receivable"
SALES_TAX_ACCOUNT = "Tax Collected"
BANK_ACCOUNT = "Bank Account"
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
        ChartOfAccountEntry(code="1000", name=posting.bank_account, type="Asset"),
        ChartOfAccountEntry(code="1200", name=SALES_RECEIVABLE_ACCOUNT, type="Asset"),
        ChartOfAccountEntry(code="1400", name=posting.tax_account, type="Asset"),
        ChartOfAccountEntry(code="2000", name=posting.payable_account, type="Liability"),
        ChartOfAccountEntry(code="2300", name=SALES_TAX_ACCOUNT, type="Liability"),
        ChartOfAccountEntry(code="4100", name=GENERIC_REVENUE_ACCOUNT, type="Revenue"),
        ChartOfAccountEntry(code="6100", name=GENERIC_EXPENSE_ACCOUNT, type="Expense"),
        ChartOfAccountEntry(code="9999", name=posting.fallback_account, type="Liability"),
    ]


def _account_name_keys(entries: list[ChartOfAccountEntry]) -> set[str]:
    return {entry.name.strip().lower() for entry in entries if entry.name.strip()}


def _next_available_code(used_codes: set[str], preferred: str) -> str:
    if preferred not in used_codes:
        return preferred
    base = int(preferred) if preferred.isdigit() else 9000
    for offset in range(1, 1000):
        candidate = str(base + offset)
        if candidate not in used_codes:
            return candidate
    return f"{preferred}x"


def merge_missing_starter_accounts(
    existing: list[ChartOfAccountEntry],
    country_code: str | None,
    *,
    posting_defaults: PostingDefaults | None = None,
) -> list[ChartOfAccountEntry]:
    """Append starter control accounts missing from an existing COA (by account name)."""
    posting = posting_defaults or PostingDefaults.for_country(country_code)
    starter = build_starter_chart_of_accounts(country_code, posting_defaults=posting)
    merged = list(existing)
    existing_names = _account_name_keys(merged)
    used_codes = {entry.code.strip() for entry in merged if entry.code.strip()}

    for entry in starter:
        name_key = entry.name.strip().lower()
        if not name_key or name_key in existing_names:
            continue
        code = _next_available_code(used_codes, entry.code)
        merged.append(ChartOfAccountEntry(code=code, name=entry.name, type=entry.type))
        existing_names.add(name_key)
        used_codes.add(code)

    return merged
