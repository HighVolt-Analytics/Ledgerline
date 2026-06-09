"""Rule book change summaries and audit detail for governance (Phase D)."""

from __future__ import annotations

from typing import Any

_RULE_LIST_KEYS = (
    "email_capture_rules",
    "purchase_rules",
    "expense_rules",
    "team_expense_rules",
    "document_sets",
)

_SCALAR_KEYS = (
    "vendor_detection_config",
    "posting_defaults",
    "legacy_cascade",
)


def _rule_rows(section: Any) -> list[dict[str, Any]]:
    if not isinstance(section, list):
        return []
    return [row for row in section if isinstance(row, dict)]


def _rule_index(rules: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for rule in rules:
        rule_id = str(rule.get("id") or "").strip()
        if rule_id:
            indexed[rule_id] = rule
    return indexed


def _rule_signature(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": rule.get("name"),
        "enabled": rule.get("enabled"),
        "priority": rule.get("priority"),
        "match_on": rule.get("match_on"),
        "post_to": rule.get("post_to"),
        "policy": rule.get("policy"),
        "action": rule.get("action"),
        "mailbox": rule.get("mailbox"),
        "root": rule.get("root"),
        "pattern": rule.get("pattern"),
        "set_name": rule.get("setName") or rule.get("set_name"),
    }


def _diff_rule_lists(
    key: str,
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
) -> dict[str, Any] | None:
    before_idx = _rule_index(before)
    after_idx = _rule_index(after)
    before_ids = set(before_idx)
    after_ids = set(after_idx)
    added = sorted(after_ids - before_ids)
    removed = sorted(before_ids - after_ids)
    modified: list[str] = []
    for rule_id in sorted(before_ids & after_ids):
        if _rule_signature(before_idx[rule_id]) != _rule_signature(after_idx[rule_id]):
            modified.append(rule_id)
    if not added and not removed and not modified:
        return None
    return {
        "before_count": len(before),
        "after_count": len(after),
        "added": added,
        "removed": removed,
        "modified": modified,
    }


def summarize_rule_book_config(config: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"schema_version": config.get("schema_version")}
    for key in _RULE_LIST_KEYS:
        rows = _rule_rows(config.get(key))
        summary[key] = {
            "count": len(rows),
            "enabled": sum(1 for row in rows if row.get("enabled", True)),
        }
    for key in _SCALAR_KEYS:
        if key in config:
            summary[key] = config.get(key)
    return summary


def diff_rule_book_config(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for key in _RULE_LIST_KEYS:
        section_diff = _diff_rule_lists(
            key,
            _rule_rows(before.get(key)),
            _rule_rows(after.get(key)),
        )
        if section_diff:
            changes[key] = section_diff

    for key in _SCALAR_KEYS:
        if before.get(key) != after.get(key):
            changes[key] = {
                "before": before.get(key),
                "after": after.get(key),
            }

    return changes
