"""QuickBooks AccountType grouped by LedgerLink GL class."""

from __future__ import annotations

from app.schemas.rule_book_config import ChartOfAccountType

PROVIDER_QBO = "quickbooks"

# Intuit AccountType → LedgerLink Type
ACCOUNT_TYPE_TO_LEDGER: dict[str, ChartOfAccountType] = {
    "Bank": "Asset",
    "Other Current Asset": "Asset",
    "Fixed Asset": "Asset",
    "Other Asset": "Asset",
    "Accounts Receivable": "Asset",
    "Equity": "Equity",
    "Expense": "Expense",
    "Other Expense": "Expense",
    "Cost of Goods Sold": "Expense",
    "Accounts Payable": "Liability",
    "Credit Card": "Liability",
    "Long Term Liability": "Liability",
    "Other Current Liability": "Liability",
    "Income": "Revenue",
    "Other Income": "Revenue",
}

CLASSIFICATION_TO_LEDGER: dict[str, ChartOfAccountType] = {
    "Asset": "Asset",
    "Liability": "Liability",
    "Equity": "Equity",
    "Revenue": "Revenue",
    "Expense": "Expense",
}

LEDGER_TYPE_TO_DEFAULT_ACCOUNT_TYPE: dict[ChartOfAccountType, str] = {
    "Asset": "Other Current Asset",
    "Liability": "Other Current Liability",
    "Equity": "Equity",
    "Revenue": "Income",
    "Expense": "Expense",
}

ACCOUNT_TYPES_BY_LEDGER: dict[ChartOfAccountType, tuple[tuple[str, str], ...]] = {
    "Asset": (
        ("Other Current Asset", "Other Current Asset"),
        ("Fixed Asset", "Fixed Asset"),
        ("Other Asset", "Other Asset"),
        ("Bank", "Bank"),
        ("Accounts Receivable", "Accounts Receivable"),
    ),
    "Liability": (
        ("Other Current Liability", "Other Current Liability"),
        ("Long Term Liability", "Long Term Liability"),
        ("Accounts Payable", "Accounts Payable"),
        ("Credit Card", "Credit Card"),
    ),
    "Equity": (("Equity", "Equity"),),
    "Revenue": (
        ("Income", "Income"),
        ("Other Income", "Other Income"),
    ),
    "Expense": (
        ("Expense", "Expense"),
        ("Other Expense", "Other Expense"),
        ("Cost of Goods Sold", "Cost of Goods Sold"),
    ),
}

# Required by Intuit when creating; must match AccountType.
DEFAULT_ACCOUNT_SUBTYPE: dict[str, str] = {
    "Bank": "Checking",
    "Other Current Asset": "OtherCurrentAssets",
    "Fixed Asset": "OtherFixedAssets",
    "Other Asset": "OtherLongTermAssets",
    "Accounts Receivable": "AccountsReceivable",
    "Equity": "OwnersEquity",
    "Expense": "OtherMiscellaneousServiceCost",
    "Other Expense": "OtherMiscellaneousExpense",
    "Cost of Goods Sold": "SuppliesMaterialsCogs",
    "Accounts Payable": "AccountsPayable",
    "Credit Card": "CreditCard",
    "Long Term Liability": "NotesPayable",
    "Other Current Liability": "OtherCurrentLiabilities",
    "Income": "OtherPrimaryIncome",
    "Other Income": "OtherMiscellaneousIncome",
}

CREATE_BLOCKED_ACCOUNT_TYPES = frozenset(
    {"Bank", "Credit Card", "Accounts Receivable", "Accounts Payable"}
)
LOCKED_ACCOUNT_TYPES = frozenset({"Accounts Receivable", "Accounts Payable"})
LOCKED_ACCOUNT_SUBTYPES = frozenset(
    {"UndepositedFunds", "RetainedEarnings", "OpeningBalanceEquity"}
)


def ledger_type_for_qbo(
    *,
    account_type: str | None,
    classification: str | None = None,
) -> ChartOfAccountType:
    typed = (account_type or "").strip()
    if typed in ACCOUNT_TYPE_TO_LEDGER:
        return ACCOUNT_TYPE_TO_LEDGER[typed]
    klass = (classification or "").strip()
    if klass in CLASSIFICATION_TO_LEDGER:
        return CLASSIFICATION_TO_LEDGER[klass]
    return "Expense"


def default_account_type(ledger_type: ChartOfAccountType) -> str:
    return LEDGER_TYPE_TO_DEFAULT_ACCOUNT_TYPE[ledger_type]


def normalize_account_type(ledger_type: ChartOfAccountType, account_type: str | None) -> str:
    allowed = {code for code, _label in ACCOUNT_TYPES_BY_LEDGER[ledger_type]}
    cleaned = (account_type or "").strip()
    if cleaned in allowed:
        return cleaned
    return default_account_type(ledger_type)


def default_account_subtype(account_type: str) -> str:
    return DEFAULT_ACCOUNT_SUBTYPE.get(account_type, "OtherMiscellaneousServiceCost")
