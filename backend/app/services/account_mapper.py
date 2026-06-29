"""Chart of accounts resolution and mapping type definitions."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.invoice import Invoice
from app.schemas.rule_book_config import RuleBookConfigPayload


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


def resolve_category_for_config(
    category: str,
    config: RuleBookConfigPayload | None = None,
) -> AccountMapping:
    """Resolve ledger/category name using tenant chart of accounts when available."""
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
    return resolve_category(cleaned)


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
    from app.services.rule_book_mapper import load_classification_config

    return await load_classification_config(session, tenant_id)


async def map_to_account(
    invoice: Invoice,
    *,
    session: AsyncSession | None = None,
    tenant_id: uuid.UUID | int | None = None,
    config: RuleBookConfigPayload | None = None,
) -> AccountMapping:
    from app.services.rule_book_mapper import map_invoice_to_account

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
    from app.services.rule_book_mapper import map_invoice_with_details

    cfg = await _resolve_config(session=session, tenant_id=tenant_id or invoice.tenant_id, config=config)
    return map_invoice_with_details(invoice, config=cfg, line_description=line_description)


async def get_tax_account_mapping(
    *,
    session: AsyncSession | None = None,
    tenant_id: uuid.UUID | int | None = None,
    config: RuleBookConfigPayload | None = None,
) -> AccountMapping:
    from app.services.rule_book_mapper import get_tax_account_mapping as _get_tax

    cfg = await _resolve_config(session=session, tenant_id=tenant_id, config=config)
    return _get_tax(cfg)


async def get_payable_account_mapping(
    *,
    session: AsyncSession | None = None,
    tenant_id: uuid.UUID | int | None = None,
    config: RuleBookConfigPayload | None = None,
) -> AccountMapping:
    from app.services.rule_book_mapper import get_payable_account_mapping as _get_payable

    cfg = await _resolve_config(session=session, tenant_id=tenant_id, config=config)
    return _get_payable(cfg)


def clear_rule_book_cache() -> None:
    from app.services.rule_book_mapper import clear_classification_config_cache

    load_chart_of_accounts.cache_clear()
    clear_classification_config_cache()
