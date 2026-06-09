"""Chart of accounts resolution and mapping type definitions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.models.invoice import Invoice


@dataclass
class AccountMapping:
    account_code: str
    account_name: str
    expense_category: str | None = None


@dataclass
class MappingDetail:
    """Expense category plus rule metadata for workbook export."""

    expense_category: str
    account_code: str
    account_name: str
    rule_type: str
    match_reason: str


@lru_cache
def load_chart_of_accounts() -> dict[str, AccountMapping]:
    path = Path(get_settings().chart_of_accounts_path)
    with path.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    return {
        category: AccountMapping(
            account_code=str(entry["account_code"]),
            account_name=str(entry["account_name"]),
            expense_category=category,
        )
        for category, entry in raw.items()
    }


def resolve_category(category: str) -> AccountMapping:
    coa = load_chart_of_accounts()
    if category in coa:
        return coa[category]
    return AccountMapping("9999", category, expense_category=category)


def map_to_account(invoice: Invoice) -> AccountMapping:
    from app.services.rule_book_mapper import map_invoice_to_account

    return map_invoice_to_account(invoice)


def map_with_details(
    invoice: Invoice,
    *,
    line_description: str | None = None,
) -> MappingDetail:
    from app.services.rule_book_mapper import map_invoice_with_details

    return map_invoice_with_details(invoice, line_description=line_description)


def get_tax_account_mapping(org_id: int) -> AccountMapping:
    from app.services.rule_book_mapper import get_tax_account_mapping as _get_tax

    return _get_tax(org_id)


def get_payable_account_mapping(org_id: int) -> AccountMapping:
    from app.services.rule_book_mapper import get_payable_account_mapping as _get_payable

    return _get_payable(org_id)


def clear_rule_book_cache() -> None:
    from app.services.rule_book_mapper import clear_classification_config_cache

    load_chart_of_accounts.cache_clear()
    clear_classification_config_cache()
