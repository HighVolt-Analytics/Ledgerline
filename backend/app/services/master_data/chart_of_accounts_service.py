"""Load and persist tenant chart of accounts (rule book config slice)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.chart_of_accounts import ChartOfAccountsResponse, UpdateChartOfAccountsRequest
from app.schemas.rule_book_config import ChartOfAccountEntry, SubLedgerEntry, validate_rule_book_config_payload
from app.services.rule_book.account_mapper import clear_rule_book_cache
from app.services.rule_book.rule_book_config_io import load_rule_book_config_dict, save_rule_book_config


async def load_chart_of_accounts(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> ChartOfAccountsResponse:
    raw = await load_rule_book_config_dict(session, tenant_id)
    payload = validate_rule_book_config_payload(raw)
    return ChartOfAccountsResponse.from_entries(payload.chart_of_accounts)


async def save_chart_of_accounts(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    body: UpdateChartOfAccountsRequest,
    *,
    updated_by_user_id: int | None = None,
) -> ChartOfAccountsResponse:
    raw = await load_rule_book_config_dict(session, tenant_id)
    payload = validate_rule_book_config_payload(raw)
    merged = payload.model_dump()
    merged["chart_of_accounts"] = [
        entry.model_dump() for entry in body.to_entries()
    ]
    updated = validate_rule_book_config_payload(merged)
    await save_rule_book_config(
        session,
        updated,
        tenant_id,
        updated_by_user_id=updated_by_user_id,
    )
    clear_rule_book_cache()
    return ChartOfAccountsResponse.from_entries(updated.chart_of_accounts)


def coa_lookup(entries: list[ChartOfAccountEntry]) -> dict[str, ChartOfAccountEntry]:
    return {entry.name.strip(): entry for entry in entries if entry.name.strip()}


def sub_ledgers_for_ledger(
    ledger_name: str,
    entries: list[ChartOfAccountEntry],
) -> list[SubLedgerEntry]:
    cleaned = (ledger_name or "").strip()
    if not cleaned:
        return []
    lookup = coa_lookup(entries)
    entry = lookup.get(cleaned)
    if entry is None:
        lowered = cleaned.lower()
        for name, candidate in lookup.items():
            if name.lower() == lowered:
                entry = candidate
                break
    if entry is None:
        return []
    return list(entry.sub_ledgers)


def sub_ledger_exists(
    ledger_name: str,
    sub_ledger_name: str,
    entries: list[ChartOfAccountEntry],
) -> bool:
    """True when sub_ledger_name matches a catalog entry under the given ledger."""
    cleaned_sub = (sub_ledger_name or "").strip()
    if not cleaned_sub:
        return False
    sub_ledgers = sub_ledgers_for_ledger(ledger_name, entries)
    if not sub_ledgers:
        return False
    lowered = cleaned_sub.lower()
    for item in sub_ledgers:
        if item.name.strip().lower() == lowered:
            return True
    return False


def ledger_has_sub_ledger_catalog(
    ledger_name: str,
    entries: list[ChartOfAccountEntry],
) -> bool:
    return bool(sub_ledgers_for_ledger(ledger_name, entries))


def _find_coa_entry(
    ledger_name: str,
    entries: list[ChartOfAccountEntry],
) -> ChartOfAccountEntry | None:
    cleaned = (ledger_name or "").strip()
    if not cleaned:
        return None
    lookup = coa_lookup(entries)
    entry = lookup.get(cleaned)
    if entry is not None:
        return entry
    lowered = cleaned.lower()
    for name, candidate in lookup.items():
        if name.lower() == lowered:
            return candidate
    return None


def parent_ledger_for_account(
    account_name: str,
    entries: list[ChartOfAccountEntry],
) -> str | None:
    """Return the budget parent for an account name.

    - If ``account_name`` is a known parent COA row, return that parent name.
    - If it matches a sub-ledger under a parent, return that parent name.
    - Otherwise return None.
    """
    cleaned = (account_name or "").strip()
    if not cleaned:
        return None
    direct = _find_coa_entry(cleaned, entries)
    if direct is not None:
        return direct.name.strip()
    lowered = cleaned.lower()
    for entry in entries:
        parent = (entry.name or "").strip()
        if not parent:
            continue
        for sub in entry.sub_ledgers or []:
            if (sub.name or "").strip().lower() == lowered:
                return parent
            if (sub.code or "").strip().lower() == lowered:
                return parent
    return None


def account_is_sub_ledger(
    account_name: str,
    entries: list[ChartOfAccountEntry],
) -> bool:
    """True when ``account_name`` is a COA child Sub-GL (not a top-level parent)."""
    cleaned = (account_name or "").strip()
    if not cleaned:
        return False
    if _find_coa_entry(cleaned, entries) is not None:
        return False
    parent = parent_ledger_for_account(cleaned, entries)
    if not parent:
        return False
    return parent.casefold() != cleaned.casefold()


def child_ledger_names(
    parent_ledger: str,
    entries: list[ChartOfAccountEntry],
) -> list[str]:
    """Parent name plus all of its COA sub-ledger names (and codes when distinct).

    Used to sum budget spend across a parent wallet and its tracking children.
    """
    parent = (parent_ledger or "").strip()
    if not parent:
        return []
    entry = _find_coa_entry(parent, entries)
    names: list[str] = []
    seen: set[str] = set()

    def _add(token: str) -> None:
        cleaned = (token or "").strip()
        if not cleaned:
            return
        key = cleaned.casefold()
        if key in seen:
            return
        seen.add(key)
        names.append(cleaned)

    if entry is not None:
        _add(entry.name)
        _add(entry.code)
        for sub in entry.sub_ledgers or []:
            _add(sub.name)
            _add(sub.code)
    else:
        _add(parent)
    return names


def budget_parent_for_claim_gl(
    claim_gl: str,
    entries: list[ChartOfAccountEntry],
    *,
    fallback_parent: str | None = None,
) -> str:
    """Resolve which parent wallet a claim GL should check against."""
    resolved = parent_ledger_for_account(claim_gl, entries)
    if resolved:
        return resolved
    fallback = (fallback_parent or "").strip()
    if fallback:
        parent = parent_ledger_for_account(fallback, entries)
        return parent or fallback
    return (claim_gl or "").strip()
