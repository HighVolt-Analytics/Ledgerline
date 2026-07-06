"""Build compact COA / sub-ledger catalogues for LLM prompts."""

from __future__ import annotations

from typing import Any, Sequence

from app.schemas.rule_book_config import ChartOfAccountEntry
from app.services.master_data.chart_of_accounts_service import sub_ledgers_for_ledger


def build_line_sub_ledger_catalogue(
    parent_ledger: str,
    accounts: Sequence[ChartOfAccountEntry],
) -> list[dict[str, str]]:
    """Return sub-ledger rows under a fixed parent GL account for line-item mapping."""
    rows: list[dict[str, str]] = []
    for entry in sub_ledgers_for_ledger(parent_ledger, list(accounts)):
        code = entry.code.strip()
        name = entry.name.strip()
        if not code or not name:
            continue
        rows.append({"code": code, "name": name})
    return rows


def parent_ledger_has_sub_ledger_catalogue(
    parent_ledger: str,
    accounts: Sequence[ChartOfAccountEntry],
) -> bool:
    return bool(build_line_sub_ledger_catalogue(parent_ledger, accounts))


def catalogue_to_prompt_lines(catalogue: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [{"code": row["code"], "name": row["name"]} for row in catalogue]
