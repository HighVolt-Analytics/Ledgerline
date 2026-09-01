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
    "fallback_account",
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
    return resolve_category_for_config(
        config.posting_defaults.fallback_account, config, _resolving_fallback=True
    )


def _find_in_chart(
    cleaned: str,
    config: RuleBookConfigPayload | None,
) -> AccountMapping | None:
    if not cleaned or config is None or not config.chart_of_accounts:
        return None
    for entry in config.chart_of_accounts:
        if entry.name == cleaned:
            return AccountMapping(entry.code, entry.name, expense_category=entry.name)
    lowered = cleaned.lower()
    for entry in config.chart_of_accounts:
        if entry.name.lower() == lowered:
            return AccountMapping(entry.code, entry.name, expense_category=entry.name)
    return None


def resolve_category_for_config(
    category: str,
    config: RuleBookConfigPayload | None = None,
    *,
    _resolving_fallback: bool = False,
) -> AccountMapping:
    """Resolve ledger/category name using THIS TENANT's own chart of accounts.

    Multi-tenant note: this must never invent a tenant-agnostic numeric code
    (the old behaviour returned a hardcoded "9999" whenever a name didn't
    match). Charts of accounts are independent per tenant, so a global magic
    code can point at nothing in one tenant's chart and at a completely
    unrelated real account in another tenant's — silently mis-posting to it.

    Instead: an unresolved name falls back to *this tenant's own configured*
    fallback/suspense account (looked up the same way, by name, in their own
    chart). Only when even that isn't configured in the chart do we give up —
    returning an empty account_code, which is not a valid GL account and is
    caught by get_unresolved_control_accounts() before anything posts.
    """
    cleaned = (category or "").strip()
    hit = _find_in_chart(cleaned, config)
    if hit is not None:
        return hit

    if _resolving_fallback or config is None:
        # Already resolving this tenant's own fallback account (or no config
        # to resolve one from) — there is nowhere safe left to park this.
        label = cleaned or "Suspense Account"
        return AccountMapping("", label, expense_category=label)

    fallback_label = (config.posting_defaults.fallback_account or "").strip() or "Suspense Account"
    fallback = resolve_category_for_config(fallback_label, config, _resolving_fallback=True)
    return AccountMapping(
        fallback.account_code,
        fallback.account_name,
        expense_category=cleaned or fallback.account_name,
    )


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
