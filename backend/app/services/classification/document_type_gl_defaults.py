"""Finance-aligned default GL account names per playbook profile."""

from __future__ import annotations

from app.schemas.rule_book_config import ChartOfAccountEntry

# Playbook profile → suggested main ledger account name (must exist in tenant COA).
SUGGESTED_LEDGER_BY_PLAYBOOK_PROFILE: dict[str, str] = {
    "po_goods": "Raw Materials",
    "import_dossier": "Raw Materials",
    "freight_logistics": "Logistics",
    "standard_transactional": "Operating Expenses",
    "credit_adjustment": "Operating Expenses",
    "debit_note": "Operating Expenses",
    "direct_expense": "Operating Expenses",
    "employee_claim": "Travel Expense",
    "ar_goods": "Operating Revenue",
    "pre_transactional": "Suspense Account",
}

COA_TYPES_BY_PLAYBOOK_PROFILE: dict[str, tuple[str, ...]] = {
    "po_goods": ("Expense", "Asset"),
    "import_dossier": ("Expense", "Asset"),
    "freight_logistics": ("Expense",),
    "standard_transactional": ("Expense",),
    "credit_adjustment": ("Expense",),
    "debit_note": ("Expense",),
    "direct_expense": ("Expense",),
    "employee_claim": ("Expense",),
    "ar_goods": ("Revenue",),
    "pre_transactional": ("Liability",),
}


def suggested_ledger_for_playbook_profile(playbook_profile: str | None) -> str:
    token = (playbook_profile or "").strip().lower()
    return SUGGESTED_LEDGER_BY_PLAYBOOK_PROFILE.get(token, "")


def coa_types_for_playbook_profile(playbook_profile: str | None) -> tuple[str, ...] | None:
    token = (playbook_profile or "").strip().lower()
    return COA_TYPES_BY_PLAYBOOK_PROFILE.get(token)


def resolve_coa_account_name(
    suggested: str,
    accounts: list[ChartOfAccountEntry],
) -> str:
    """Match a suggested ledger name against tenant chart of accounts."""
    needle = (suggested or "").strip()
    if not needle or not accounts:
        return ""
    for entry in accounts:
        if entry.name == needle:
            return entry.name
    lowered = needle.lower()
    for entry in accounts:
        if entry.name.lower() == lowered:
            return entry.name
    for entry in accounts:
        name_lower = entry.name.lower()
        if lowered in name_lower or name_lower in lowered:
            return entry.name
    return ""


def _resolve_sparse_revenue_ledger(accounts: list[ChartOfAccountEntry]) -> str:
    revenue = [entry for entry in accounts if (entry.type or "") == "Revenue"]
    if len(revenue) == 1:
        return revenue[0].name
    import re

    hint = re.compile(r"\b(sales|revenue|income|turnover)\b", re.I)
    for entry in revenue:
        if hint.search(entry.name or ""):
            return entry.name
    return ""


def default_post_to_ledger(
    playbook_profile: str | None,
    accounts: list[ChartOfAccountEntry],
    *,
    route_target: str | None = None,
) -> str:
    suggested = suggested_ledger_for_playbook_profile(playbook_profile)
    if suggested:
        resolved = resolve_coa_account_name(suggested, accounts)
        if resolved:
            return resolved
    profile = (playbook_profile or "").strip().lower()
    route = (route_target or "").strip()
    if profile == "ar_goods" or route == "Sales Management":
        return _resolve_sparse_revenue_ledger(accounts)
    return ""
