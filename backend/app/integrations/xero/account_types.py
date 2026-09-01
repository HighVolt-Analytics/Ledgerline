"""Xero AccountType (sub type) grouped by LedgerLink GL class."""

from __future__ import annotations

from app.schemas.rule_book_config import ChartOfAccountType

# Xero Type code → LedgerLink Type
SUBTYPE_TO_LEDGER_TYPE: dict[str, ChartOfAccountType] = {
    "BANK": "Asset",
    "CURRENT": "Asset",
    "FIXED": "Asset",
    "NONCURRENT": "Asset",
    "INVENTORY": "Asset",
    "PREPAYMENT": "Asset",
    "CURRLIAB": "Liability",
    "TERMLIAB": "Liability",
    "LIABILITY": "Liability",
    "EQUITY": "Equity",
    "REVENUE": "Revenue",
    "SALES": "Revenue",
    "OTHERINCOME": "Revenue",
    "EXPENSE": "Expense",
    "DIRECTCOSTS": "Expense",
    "OVERHEADS": "Expense",
    "DEPRECIATN": "Expense",
}

CLASS_TO_LEDGER_TYPE: dict[str, ChartOfAccountType] = {
    "ASSET": "Asset",
    "LIABILITY": "Liability",
    "EQUITY": "Equity",
    "REVENUE": "Revenue",
    "EXPENSE": "Expense",
}

LEDGER_TYPE_TO_DEFAULT_SUBTYPE: dict[ChartOfAccountType, str] = {
    "Asset": "CURRENT",
    "Liability": "CURRLIAB",
    "Equity": "EQUITY",
    "Revenue": "REVENUE",
    "Expense": "EXPENSE",
}

SUBTYPES_BY_LEDGER_TYPE: dict[ChartOfAccountType, tuple[tuple[str, str], ...]] = {
    "Asset": (
        ("CURRENT", "Current Asset"),
        ("BANK", "Bank"),
        ("FIXED", "Fixed Asset"),
        ("NONCURRENT", "Non-current Asset"),
        ("INVENTORY", "Inventory"),
        ("PREPAYMENT", "Prepayment"),
    ),
    "Liability": (
        ("CURRLIAB", "Current Liability"),
        ("TERMLIAB", "Non-current Liability"),
        ("LIABILITY", "Liability"),
    ),
    "Equity": (("EQUITY", "Equity"),),
    "Revenue": (
        ("REVENUE", "Revenue"),
        ("SALES", "Sales"),
        ("OTHERINCOME", "Other Income"),
    ),
    "Expense": (
        ("EXPENSE", "Expense"),
        ("DIRECTCOSTS", "Direct Costs"),
        ("OVERHEADS", "Overhead"),
        ("DEPRECIATN", "Depreciation"),
    ),
}

XERO_DEFAULT_TAX_TYPE = "BASEXCLUDED"
PROVIDER_XERO = "xero"


def ledger_type_for_xero(
    *,
    account_type: str | None,
    account_class: str | None = None,
) -> ChartOfAccountType:
    subtype = (account_type or "").strip().upper()
    if subtype in SUBTYPE_TO_LEDGER_TYPE:
        return SUBTYPE_TO_LEDGER_TYPE[subtype]
    klass = (account_class or "").strip().upper()
    if klass in CLASS_TO_LEDGER_TYPE:
        return CLASS_TO_LEDGER_TYPE[klass]
    return "Expense"


def default_subtype(ledger_type: ChartOfAccountType) -> str:
    return LEDGER_TYPE_TO_DEFAULT_SUBTYPE[ledger_type]


def normalize_subtype(ledger_type: ChartOfAccountType, subtype: str | None) -> str:
    allowed = {code for code, _label in SUBTYPES_BY_LEDGER_TYPE[ledger_type]}
    cleaned = (subtype or "").strip().upper()
    if cleaned in allowed:
        return cleaned
    return default_subtype(ledger_type)
