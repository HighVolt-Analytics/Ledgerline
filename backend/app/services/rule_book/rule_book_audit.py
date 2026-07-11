"""Rule book change summaries and audit detail for governance (Phase D)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.schemas.rule_book_config import validate_rule_book_config_payload
from app.services.audit.audit_service import log_event
from app.services.rule_book.rule_book_config_io import load_rule_book_config_dict
from app.utils.logger import get_logger

logger = get_logger(__name__)

_RULE_LIST_KEYS = (
    "document_types",
    "email_capture_rules",
    "purchase_rules",
    "sales_rules",
    "expense_rules",
    "team_expense_rules",
    "document_sets",
)

_SCALAR_KEYS = (
    "document_classification",
    "org_context",
    "ai_classification",
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
        rule_id = str(rule.get("id") or rule.get("code") or "").strip()
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
        "route_target": rule.get("route_target"),
        "classifier": rule.get("classifier"),
        "title": rule.get("title"),
        "klass": rule.get("klass"),
        "posting": rule.get("posting"),
        "match_policy": rule.get("match_policy") or rule.get("matchPolicy"),
        "approval_policy": rule.get("approval_policy") or rule.get("approvalPolicy"),
        "playbook_profile": rule.get("playbook_profile") or rule.get("playbookProfile"),
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


def normalize_rule_book_for_diff(raw: dict[str, Any]) -> dict[str, Any]:
    """Canonicalise config so pydantic defaults do not appear as rule edits."""
    payload = dict(raw)
    payload["vendor_masters"] = []
    payload["employee_masters"] = []
    return validate_rule_book_config_payload(payload).model_dump()


_RULE_COMPARE_EXCLUDE = frozenset({"matched_count", "last_matched"})


def _rule_config_for_compare(rule: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in rule.items() if key not in _RULE_COMPARE_EXCLUDE}


def _deep_values_equal(left: Any, right: Any) -> bool:
    if left is None and right is None:
        return True
    if isinstance(left, dict) and isinstance(right, dict):
        keys = set(left) | set(right)
        return all(_deep_values_equal(left.get(key), right.get(key)) for key in keys)
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return False
        return all(_deep_values_equal(a, b) for a, b in zip(left, right, strict=True))
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    return left == right


def _rule_configs_differ(before_rule: dict[str, Any], after_rule: dict[str, Any]) -> bool:
    before_fields = _rule_config_for_compare(before_rule)
    after_fields = _rule_config_for_compare(after_rule)
    keys = set(before_fields) | set(after_fields)
    for key in keys:
        if not _deep_values_equal(before_fields.get(key), after_fields.get(key)):
            return True
    return False


def truly_modified_rule_ids(
    section_key: str,
    before: dict[str, Any],
    after: dict[str, Any],
    candidate_ids: list[str],
) -> list[str]:
    """Rule IDs whose full config differs between before and after."""
    before_idx = _rule_index(_rule_rows(before.get(section_key)))
    after_idx = _rule_index(_rule_rows(after.get(section_key)))
    modified: list[str] = []
    for rule_id in candidate_ids:
        before_rule = before_idx.get(rule_id)
        after_rule = after_idx.get(rule_id)
        if before_rule is None or after_rule is None:
            modified.append(rule_id)
            continue
        if _rule_configs_differ(before_rule, after_rule):
            modified.append(rule_id)
    return modified


def filter_auditable_rule_book_changes(
    changes: dict[str, Any],
    *,
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    """Drop spurious modified rule IDs where before/after configs are identical."""
    filtered: dict[str, Any] = {}
    for section_key, section in changes.items():
        if section_key in _RULE_LIST_KEYS and isinstance(section, dict):
            added = list(section.get("added") or [])
            removed = list(section.get("removed") or [])
            modified = truly_modified_rule_ids(
                section_key,
                before,
                after,
                list(section.get("modified") or []),
            )
            if not added and not removed and not modified:
                continue
            filtered[section_key] = {
                **section,
                "added": added,
                "removed": removed,
                "modified": modified,
            }
        else:
            filtered[section_key] = section
    return filtered


def rule_book_changes_are_auditable(
    changes: dict[str, Any],
    *,
    before: dict[str, Any],
    after: dict[str, Any],
) -> bool:
    """True when rules were added/removed or a modified rule's config actually changed."""
    auditable = filter_auditable_rule_book_changes(changes, before=before, after=after)
    if not auditable:
        return False
    for section_key, section in auditable.items():
        if section_key not in _RULE_LIST_KEYS or not isinstance(section, dict):
            continue
        if section.get("added") or section.get("removed") or section.get("modified"):
            return True
    return False


def rule_book_content_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Deep-compare normalised rule book configs (rules + scalar sections)."""
    return _deep_values_equal(
        normalize_rule_book_for_diff(left),
        normalize_rule_book_for_diff(right),
    )


def extract_rule_book_content_from_audit_detail(
    detail: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(detail, dict):
        return None
    content = detail.get("content")
    if isinstance(content, dict):
        return content
    return None


async def fetch_last_rule_book_updated(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> AuditLog | None:
    return (
        await session.execute(
            select(AuditLog)
            .where(
                AuditLog.tenant_id == tenant_id,
                AuditLog.event == "rule_book_updated",
            )
            .order_by(AuditLog.id.desc())
            .limit(1)
        )
    ).scalars().first()


async def is_duplicate_rule_book_update(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    incoming_content: dict[str, Any],
) -> bool:
    """True when incoming config matches the last persisted rule_book_updated snapshot."""
    last = await fetch_last_rule_book_updated(session, tenant_id)
    if last is None:
        return False

    prior_content = extract_rule_book_content_from_audit_detail(
        last.detail if isinstance(last.detail, dict) else None
    )
    if prior_content is None:
        try:
            prior_content = normalize_rule_book_for_diff(
                await load_rule_book_config_dict(session, tenant_id)
            )
        except (FileNotFoundError, ValueError):
            return False

    return rule_book_content_equal(prior_content, incoming_content)


async def log_rule_book_updated(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    after_config: dict[str, Any],
    detail: dict[str, Any],
    actor_name: str | None = None,
    actor_email: str | None = None,
    client_ip: str | None = None,
) -> AuditLog | None:
    """Write rule_book_updated unless content is identical to the last audit row for this org."""
    if await is_duplicate_rule_book_update(session, tenant_id, after_config):
        logger.info("rule_book_updated_suppressed_duplicate", tenant_id=tenant_id)
        return None

    return await log_event(
        session,
        "rule_book_updated",
        tenant_id=tenant_id,
        detail={**detail, "content": after_config},
        actor_name=actor_name,
        actor_email=actor_email,
        client_ip=client_ip,
    )
