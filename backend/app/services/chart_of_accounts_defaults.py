"""Default chart of accounts seeded for new tenants."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import get_settings
from app.schemas.rule_book_config import _infer_chart_of_account_type


def global_default_chart_entries() -> list[dict[str, str]]:
    path = Path(get_settings().chart_of_accounts_path)
    with path.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    entries: list[dict[str, str]] = []
    for _category, entry in raw.items():
        name = str(entry["account_name"])
        entries.append(
            {
                "code": str(entry["account_code"]),
                "name": name,
                "type": _infer_chart_of_account_type(name),
            }
        )
    return entries
