"""Chart of accounts resolution and mapping type definitions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.schemas.rule_book_config import RuleBookConfigPayload

ControlAccountRole = Literal[
    "payable_account",
    "receivable_account",
    "tax_account",
    "settlement_account",
    "staff_advance_account",
]


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


def category_resolved_in_coa(
    category: str,
    config: RuleBookConfigPayload | None = None,
) -> bool:
    """True when category name matches a chart_of_accounts entry (case-insensitive)."""
    cleaned = (category or "").strip()
    if not cleaned or config is None or not config.chart_of_accounts:
        return False
    for entry in config.chart_of_accounts:
        if entry.name == cleaned:
            return True
    lowered = cleaned.lower()
    for entry in config.chart_of_accounts:
        if entry.name.lower() == lowered:
            return True
    return False


_SALES_RECEIVABLE_ACCOUNT = "Accounts Receivable"
_SALES_TAX_ACCOUNT = "Tax Collected"


def coa_functional_for_journaling(config: RuleBookConfigPayload) -> bool:
    """True when control accounts required for purchase and sales journals resolve in COA."""
    defaults = config.posting_defaults
    receivable = (defaults.receivable_account or "").strip() or _SALES_RECEIVABLE_ACCOUNT
    required = [
        defaults.payable_account,
        defaults.tax_account,
        defaults.fallback_account,
        defaults.bank_account,
        receivable,
        _SALES_TAX_ACCOUNT,
    ]
    return all(category_resolved_in_coa(name, config) for name in required)


def resolve_fallback_account_mapping(
    config: RuleBookConfigPayload,
) -> AccountMapping:
    return resolve_category_for_config(config.posting_defaults.fallback_account, config)


def resolve_category_for_config(
    category: str,
    config: RuleBookConfigPayload | None = None,
) -> AccountMapping:
    """Resolve ledger/category name using the tenant chart of accounts."""
    cleaned = (category or "").strip()
    if not cleaned:
        return AccountMapping("9999", "Suspense Account", expense_category="Suspense Account")
    if config is not None and config.chart_of_accounts:
        for entry in config.chart_of_accounts:
            if entry.name == cleaned:
                return AccountMapping(entry.code, entry.name, expense_category=entry.name)
        lowered = cleaned.lower()
        for entry in config.chart_of_accounts:
            if entry.name.lower() == lowered:
                return AccountMapping(entry.code, entry.name, expense_category=entry.name)
    return AccountMapping("9999", cleaned, expense_category=cleaned)


async def _resolve_config(
    *,
    session: AsyncSession | None,
    tenant_id: uuid.UUID | int | None,
    config: RuleBookConfigPayload | None,
) -> RuleBookConfigPayload:
    if config is not None:
        return config
    if session is None or tenant_id is None:
        raise ValueError("Provide config or (session, tenant_id)")
    from app.services.rule_book.rule_book_mapper import load_classification_config

    return await load_classification_config(session, tenant_id)


async def map_to_account(
    invoice: Invoice,
    *,
    session: AsyncSession | None = None,
    tenant_id: uuid.UUID | int | None = None,
    config: RuleBookConfigPayload | None = None,
) -> AccountMapping:
    from app.services.rule_book.rule_book_mapper import map_invoice_to_account

    cfg = await _resolve_config(session=session, tenant_id=tenant_id or invoice.tenant_id, config=config)
    return map_invoice_to_account(invoice, config=cfg)


async def map_with_details(
    invoice: Invoice,
    *,
    line_description: str | None = None,
    session: AsyncSession | None = None,
    tenant_id: uuid.UUID | int | None = None,
    config: RuleBookConfigPayload | None = None,
) -> MappingDetail:
    from app.services.rule_book.rule_book_mapper import map_invoice_with_details

    cfg = await _resolve_config(session=session, tenant_id=tenant_id or invoice.tenant_id, config=config)
    return map_invoice_with_details(invoice, config=cfg, line_description=line_description)


async def get_tax_account_mapping(
    *,
    session: AsyncSession | None = None,
    tenant_id: uuid.UUID | int | None = None,
    config: RuleBookConfigPayload | None = None,
) -> AccountMapping:
    from app.services.rule_book.rule_book_mapper import get_tax_account_mapping as _get_tax

    cfg = await _resolve_config(session=session, tenant_id=tenant_id, config=config)
    return _get_tax(cfg)


async def get_payable_account_mapping(
    *,
    session: AsyncSession | None = None,
    tenant_id: uuid.UUID | int | None = None,
    config: RuleBookConfigPayload | None = None,
) -> AccountMapping:
    from app.services.rule_book.rule_book_mapper import get_payable_account_mapping as _get_payable

    cfg = await _resolve_config(session=session, tenant_id=tenant_id, config=config)
    return _get_payable(cfg)


def clear_rule_book_cache() -> None:
    from app.services.rule_book.rule_book_mapper import clear_classification_config_cache

    clear_classification_config_cache()
