"""Non-blocking validation warnings for email capture rules."""

from __future__ import annotations

from typing import Any

from app.schemas.rule_book_config import EmailCaptureRule, RuleConditionGroup

_EMPTY_VALUE_OPERATORS = frozenset({"contains", "not_contains", "starts_with", "ends_with"})


def _walk_conditions(root: dict[str, Any]) -> list[dict[str, Any]]:
    leaves: list[dict[str, Any]] = []
    for child in root.get("children") or []:
        if not isinstance(child, dict):
            continue
        if child.get("type") == "group":
            leaves.extend(_walk_conditions(child))
        elif child.get("type") == "condition":
            leaves.append(child)
    return leaves


def _is_trivially_true_tree(root: dict[str, Any]) -> bool:
    leaves = _walk_conditions(root)
    if not leaves:
        return True
    operator = str(root.get("operator") or "AND").upper()
    if operator == "AND":
        return all(_condition_is_trivially_true(leaf) for leaf in leaves)
    return any(_condition_is_trivially_true(leaf) for leaf in leaves)


def _condition_is_trivially_true(condition: dict[str, Any]) -> bool:
    op = str(condition.get("operator") or "")
    value = str(condition.get("value") or "").strip()
    if op in _EMPTY_VALUE_OPERATORS and not value:
        return False
    if op == "contains" and not value:
        return False
    if op == "regex" and not value.strip():
        return True
    return False


def validate_rule_disconnected_mailbox(
    rule: EmailCaptureRule,
    connected_mailbox_emails: set[str],
) -> list[str]:
    """Warn when a rule targets a mailbox that is not connected for this tenant."""
    mailbox = (rule.mailbox or "").strip().lower()
    if not mailbox or mailbox == "*":
        return []
    if mailbox in connected_mailbox_emails:
        return []
    return [
        f'Rule "{rule.name}" targets mailbox {rule.mailbox}, which is not connected — '
        "it is ignored at ingest until that mailbox is linked or the rule is removed."
    ]


def validate_rule_specificity(
    rule: EmailCaptureRule,
    *,
    connected_mailbox_emails: set[str] | None = None,
) -> list[str]:
    """Return human-readable warnings for overly broad or invalid rule conditions."""
    warnings: list[str] = []
    if connected_mailbox_emails is not None:
        warnings.extend(validate_rule_disconnected_mailbox(rule, connected_mailbox_emails))
    root = rule.root.model_dump() if isinstance(rule.root, RuleConditionGroup) else dict(rule.root)

    mailbox = (rule.mailbox or "").strip()
    if mailbox in {"", "*"}:
        if _is_trivially_true_tree(root):
            warnings.append(
                f'Rule "{rule.name}" applies to all mailboxes (*) with empty or trivially-true '
                "conditions — it would match every attachment."
            )

    for leaf in _walk_conditions(root):
        op = str(leaf.get("operator") or "")
        value = str(leaf.get("value") or "").strip()
        field = str(leaf.get("field") or "")
        if op in _EMPTY_VALUE_OPERATORS and not value:
            warnings.append(
                f'Rule "{rule.name}" has an empty value for {field} / {op} — '
                "this condition will never match."
            )

    return warnings


def validate_email_capture_rules_specificity(rules: list[EmailCaptureRule]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for rule in rules:
        for warning in validate_rule_specificity(rule):
            if warning not in seen:
                seen.add(warning)
                out.append(warning)
    return out


def validate_email_capture_rules_warnings_by_id(
    rules: list[EmailCaptureRule],
    *,
    connected_mailbox_emails: set[str] | None = None,
) -> dict[str, list[str]]:
    """Map rule id -> validation warnings (for inline UI)."""
    out: dict[str, list[str]] = {}
    for rule in rules:
        warnings = validate_rule_specificity(
            rule,
            connected_mailbox_emails=connected_mailbox_emails,
        )
        if warnings:
            out[rule.id] = warnings
    return out
